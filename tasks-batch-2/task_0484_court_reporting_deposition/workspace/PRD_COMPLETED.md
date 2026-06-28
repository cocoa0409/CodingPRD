# Court Reporting & Deposition API — Product Requirements Document

## 1. Introduction

Litigation depositions sit at the intersection of scheduling, skilled-labor coordination, and downstream document production, and the operational reality is messy: a single deposition requires a certified court reporter, sometimes a videographer or a language interpreter, occasionally a live real-time text feed, and — once the witness has been examined — a transcript that must be drafted, certified, read, corrected, signed, and finally e-delivered before anyone can be billed. This API exists to model that entire arc as a single coherent system of record, so that a scheduling desk, the reporters and videographers in the field, the noticing attorneys, and the billing back-office all act against one consistent source of truth.

The system governs five intertwined concerns. It schedules **jobs** (the depositions themselves) under **cases**, and staffs them by joining **resources** (reporters, videographers, interpreters) to jobs through **assignments**, guarding against double-booking and credential mismatches. It opens and closes the deposition session, provisioning an optional **real-time stream** for live transcript delivery. After a job adjourns it tracks the **transcript order** through its production and read-and-sign lifecycle, including **exhibits** marked into the record and the cyclic **errata** correction process by which a deponent amends testimony. Finally it reconciles **invoices** that fold appearance fees, page-rate charges, and exhibit charges into a single billed total. Throughout, a logical clock drives every deadline and scheduling-window evaluation so that the system's temporal behavior is deterministic and testable rather than tied to wall-clock time.

Because depositions are scheduled and re-staffed concurrently by a busy coordination desk, the system treats the job as the unit of contention and applies optimistic concurrency control to assignment creation. Pricing is likewise treated as a first-class concern: estimates are offered up-front for quoting, while authoritative billed values are frozen at the moments the underlying facts become final — when a session adjourns, when a transcript is certified, and when an invoice is issued.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled precisely as follows: `ScheduleCoordinator`, `Reporter`, `Attorney`, `BillingClerk`, and `PlatformAdmin`. When an authenticated role attempts an operation that the role-based access matrix does not grant it, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role, because some roles are backed by a persisted entity and others are opaque operators. When `X-User-Role` is `Reporter`, `X-User-ID` is the `id` of the acting `Resource`; ownership checks on any resource that references a `Resource` (for example, a transcript order's delivering or certifying reporter) compare the relevant assignment's `resource_id` to `X-User-ID`. When `X-User-Role` is `Attorney`, `X-User-ID` is the `id` of the acting `Attorney`; ownership checks compare the resource's attorney foreign key to `X-User-ID` — specifically, an attorney acting on a transcript must match either that transcript order's `ordering_attorney_id` or the noticing attorney recorded on the job's case (`noticing_attorney_id`), and a mismatch is rejected with `ERR_NOT_CASE_PARTY` (HTTP 403). When `X-User-Role` is `ScheduleCoordinator`, `BillingClerk`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. `PlatformAdmin` is an operational superset that may perform any business operation of any other role in addition to its own exclusive capabilities.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is drawn from the server logical clock (§2.8), so on both success and error responses it reflects the current logical-clock value rather than host wall-clock time.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

Every list-style response includes these fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

All ten primary entities — Case, Attorney, Resource, Job, Assignment, RealtimeStream, TranscriptOrder, Exhibit, Errata, and Invoice — carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created, and `updated_at` is the analogous timestamp of the most recent modification. `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource. Because every entity in this domain carries the full common-field set, all of them expose `updated_at` and `version`; none is a create-only record that omits them.

Whenever the server derives a field rather than accepting it as input — for example a job's `staffing_posture`, an assignment's `appearance_fee_cents`, or an invoice's reconciled `total_cents` — recomputing and storing that derived value counts as a mutation, so it refreshes `updated_at` and increments `version` on the owning resource. The same is true when a cascade reaches into a resource: if cancelling a job releases an assignment, the assignment is itself mutated.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource nested beneath a parent, such as the assignments under a job or the exhibits under a transcript order. For any request whose path carries more than one identifier, the system validates existence left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. The same 404 governs foreign-key references supplied in a request body: if a body field names a parent or related resource that does not exist, the request is rejected with `ERR_NOT_FOUND`. Existence is checked before any state or business rule particular to the operation, so that an invalid container is always caught before the system attempts to evaluate the nested resource.

### 2.6. Optimistic Concurrency Control on Job Staffing

The deposition job is the unit of contention in this system because multiple coordinators staff and re-staff the same job, and each assignment change legitimately alters the job's staffing posture and the set of roles already occupied. To prevent a coordinator from acting on a stale picture of a job, assignment creation is guarded by optimistic concurrency control. A request that assigns a resource to a job must carry `expected_job_version`, a non-optional field that conveys the client's last observed `version` of the target `Job`. If `expected_job_version` does not equal the job's current `version` — that is, if another writer has added or released an assignment on that job since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from creating an assignment against a view of the job's open roles that is out of date. This optimistic-concurrency guard applies only to assignment creation; no other endpoint accepts or requires a version field.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts in this system are integers denominated in **cents** — appearance rates, page-rate charges, exhibit charges, certification flat fees, and invoice subtotals and totals are all whole-cent integers. Where a calculation multiplies by a fractional factor (a tier discount, an expedite multiplier, or the real-time surcharge), the result is rounded to the nearest whole cent using the **round half up** convention, meaning a value exactly halfway between two cents rounds up to the larger cent. The precise point in each formula at which rounding occurs is part of the specification and is stated alongside each calculation in §3; rounding is never applied loosely or at an arbitrary step.

### 2.8. The Logical Clock and Temporal Determinism

Every deadline and scheduling-window evaluation in the system reads a single server-maintained **logical clock** rather than wall-clock time. At startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and until an administrator explicitly sets it, it remains at that default and never falls back to the host's real time. An administrative test-driving capability sets the clock to the absolute ISO 8601 UTC instant supplied as `to_iso8601`, after which all future-dating checks (such as confirming a job whose start must still be ahead), session-open gating, real-time timestamps, and the thirty-day read-and-sign deadline are evaluated against the new clock value. Setting the clock returns the new `current_utc`.

### 2.9. Cascades and Hierarchical Consistency

Several operations mutate more than one entity, and the secondary effects are as much a part of the contract as the primary state change. Cancelling a job releases every active assignment on it and resets the job's staffing posture. Adjourning a job completes its active assignments, freezes each one's appearance fee, and stops any running real-time stream. Each entity touched by such a cascade is independently mutated — its `updated_at` and `version` advance — and the precise membership and ordering of these cascades is specified in the workflow narratives of §3. A derived field that depends on child state, such as a job's staffing posture, is recomputed whenever the children that feed it change.

## 3. Business Logic & Workflows

### 3.1. Cases, Attorneys, and Resources: the Reference Data

Before any deposition can be scheduled, the reference entities must exist. A **case** is the litigation file under which depositions are noticed. A `ScheduleCoordinator` (or a `PlatformAdmin`) opens a case by supplying its `caption` — the full case caption, which must be non-empty — and its `docket_number`, the court's case number, which must be non-empty and unique across all cases; a second case attempting to reuse a docket number is rejected with `ERR_DUPLICATE_KEY`. The case also carries a `jurisdiction`, which must be one of `FEDERAL`, `STATE_CA`, `STATE_NY`, or `STATE_TX`, and which later drives the per-page transcript rate and the certification ruleset. Finally the case names its `noticing_attorney_id`, the foreign key to the attorney party that owns the file; that attorney must already exist.

An **attorney** is registered with a non-empty `full_name`, a non-empty `firm_name`, a `bar_state` drawn from `CA`, `NY`, `TX`, or `FED` (the state bar admission; this is recorded descriptively only — the system does not check `bar_state` against any case `jurisdiction` at case-open or job-notice time, so an attorney may notice a case in any jurisdiction regardless of their bar), and an `email` that serves both as contact and as e-delivery address. The email must be non-empty and unique across all attorneys; a duplicate is rejected with `ERR_DUPLICATE_KEY`.

A **resource** is a person who can be staffed onto depositions — a court reporter, a videographer, or a language interpreter. Registration captures a non-empty `full_name`, a `kind` of `REPORTER`, `VIDEOGRAPHER`, or `INTERPRETER` (which gates the assignment role the resource may fill), and an `hourly_appearance_cents` per-hour appearance rate in cents that must be zero or greater; a negative value is rejected with `ERR_INVALID_REQUEST`. The optional `certifications` array holds held credential codes — reporter credentials such as `CSR_CA`, `RPR`, or `RMR`, and language codes for interpreters — and defaults to an empty list when omitted. The optional boolean `realtime_capable` records whether a reporter can drive a live feed; it defaults to false and is ignored for non-reporters. Every resource also carries a system-managed `active` flag that defaults to true on registration. An administrator may deactivate a resource, which sets `active` to false and advances the resource's `version`; deactivation is a soft-availability change — an inactive resource cannot be staffed onto a new assignment but keeps every assignment it already holds.

### 3.2. Noticing and Staffing a Deposition Job

A deposition is represented by a **job**, noticed by a `ScheduleCoordinator` against an existing case. The notice supplies the `case_id`, the non-empty `deponent_name` of the witness, and the session window as `scheduled_start` (inclusive) and `scheduled_end` (exclusive), both ISO 8601 UTC. The end must be strictly after the start; a window where `scheduled_end` is not strictly later than `scheduled_start` is rejected with `ERR_INVALID_TIME_WINDOW`. The notice also declares the staffing requirements as booleans: `requires_videographer` and `requires_interpreter` (each defaulting to false) and `requires_realtime` (also defaulting to false), the last of which forces the reporter on the job to be real-time capable. When an interpreter is required, the notice carries `interpreter_language`, the language code matched against an interpreter's certifications; it defaults to null. A freshly noticed job enters `status` `NOTICED` and `staffing_posture` `UNSTAFFED`, with the session-outcome timestamps `actual_start` and `actual_end` both null until the session runs. A job's lifecycle `status` is always one of `NOTICED`, `CONFIRMED`, `IN_SESSION`, `ADJOURNED`, or `CANCELLED`.

Staffing a job means creating an **assignment** that joins a resource to the job in a particular `role`, supplied alongside the `resource_id` (and the OCC field `expected_job_version` described in §2.6). The role must be one of `REPORTER`, `VIDEOGRAPHER`, or `INTERPRETER`. A new assignment begins in `status` `ACTIVE`; an assignment's status is always one of `ACTIVE`, `RELEASED`, or `COMPLETED`. Its `appearance_fee_cents` field is present from creation but holds 0 until the job adjourns and the fee is computed.

Creating an assignment runs a battery of checks, and their relative priority matters because the first failing check determines which error the caller sees. Authentication is evaluated first, then role authorization, then the existence of every referenced resource (the job and the named resource), as described in §2.1 and §2.5. After existence, the optimistic-concurrency guard of §2.6 compares `expected_job_version` to the job's current `version` and rejects a mismatch with `ERR_STALE_VERSION`. The business checks then proceed in this order. First, the assignment `role` must equal the referenced resource's `kind`; a mismatch is `ERR_ROLE_KIND_MISMATCH`. Next, the resource must be active — assigning a resource whose `active` is false is rejected with `ERR_RESOURCE_INACTIVE`. Then the job may hold at most one active assignment per role, so attempting to add a second active reporter, videographer, or interpreter is rejected with `ERR_ROLE_ALREADY_FILLED`. If the role is `INTERPRETER`, the resource's `certifications` must contain the job's `interpreter_language`, failing which the system returns `ERR_INTERPRETER_LANGUAGE_MISMATCH`. If the role is `REPORTER` and the job requires real-time, the resource's `realtime_capable` must be true, failing which the system returns `ERR_REALTIME_NOT_CAPABLE`. After these eligibility checks come the temporal conflict checks described in §3.3.

### 3.3. Avoiding Double-Booking: Window and Buffer Conflicts

A resource's time is committed by its active assignments, and the system protects each resource against overlapping or too-tightly-spaced commitments. Each job defines a half-open occupancy window running from its `scheduled_start` up to but not including its `scheduled_end`. When a new assignment is proposed, the system checks every other active assignment held by that same resource: if any of those assignments belongs to a job whose half-open window overlaps the new job's half-open window, the assignment is rejected with `ERR_RESOURCE_DOUBLE_BOOKED`. Because the windows are half-open, two jobs that merely touch — one ending at exactly the instant the next begins — do not overlap and are permitted.

Reporters are held to a stricter standard. In addition to the no-overlap rule, a reporter assignment must respect a thirty-minute travel buffer between adjacent job windows on the same reporter. Even when two job windows do not overlap, if the gap between one job's end and the adjacent job's start is less than thirty minutes, the reporter assignment is rejected with `ERR_REPORTER_BUFFER_CONFLICT`. This buffer applies only to reporter assignments; videographers and interpreters are subject only to the overlap rule. Within the assignment-creation priority order, the plain overlap check is evaluated before the reporter buffer check.

Releasing an assignment is the inverse of staffing. A `ScheduleCoordinator` may release an assignment that is `ACTIVE`, but only while the parent job is still `NOTICED` or `CONFIRMED`; once the job is `IN_SESSION` or `ADJOURNED` the assignment can no longer be released, and an attempt is rejected as an invalid state transition with `ERR_INVALID_STATE`. Releasing moves the assignment from `ACTIVE` to `RELEASED`, which frees that resource's `[scheduled_start, scheduled_end)` window so it no longer counts against future overlap checks, and triggers a recomputation of the parent job's staffing posture, which may drop the job from `READY` back to `PARTIAL`.

### 3.4. Staffing Posture: When a Job Is Ready

A job's `staffing_posture` is a derived field, recomputed whenever an assignment is created or released and whenever a job is cancelled, and it summarizes whether the job's required roles are covered by current active assignments. The required-role set always includes `REPORTER`; it additionally includes `VIDEOGRAPHER` when the job requires a videographer, and `INTERPRETER` when the job requires an interpreter. The system then looks only at the job's `ACTIVE` assignments — released and completed assignments are excluded — and determines which required roles are covered, where a role counts as covered only if its assignment satisfies the same per-role eligibility used at assignment time (in particular, when the job requires real-time, the reporter assignment counts toward coverage only if its resource is real-time capable). If every required role is covered, the posture is `READY`. If no required role is covered at all, the posture is `UNSTAFFED`. Otherwise — some but not all required roles covered — the posture is `PARTIAL`. The comparison is a plain set comparison over roles with no rounding involved.

### 3.5. Running the Session: Confirm, Start, Adjourn, Cancel

Once a job is fully staffed, a `ScheduleCoordinator` confirms it, advancing it from `NOTICED` to `CONFIRMED`. Confirmation requires that the job be `NOTICED`, that the job's staffing posture is `READY` — every required role covered — and that the job's `scheduled_start` is still strictly in the future relative to the logical clock (clock strictly before `scheduled_start`); if any of these preconditions fails the transition is rejected with `ERR_INVALID_STATE`. Confirmation recomputes the staffing posture and increments the job's `version`.

Starting the session advances a `CONFIRMED` job to `IN_SESSION`. This requires the job to be `CONFIRMED` and the logical clock to have reached or passed the job's `scheduled_start` (the clock is at or after `scheduled_start`); a failure of either precondition is rejected with `ERR_INVALID_STATE`. Starting stamps `actual_start` with the current logical clock value and increments `version`. Adjourning then advances an `IN_SESSION` job to `ADJOURNED`, the terminal state in which a transcript may be ordered. Adjournment requires the job to be `IN_SESSION`; it stamps `actual_end` with the logical clock and increments `version`. Adjournment also fires a multi-part cascade: first, every `ACTIVE` assignment on the job transitions to `COMPLETED`; second, each newly completed assignment has its `appearance_fee_cents` computed from the job's `actual_start` and `actual_end` as described in §3.6; and finally, any real-time stream on the job that is still `STARTING` or `LIVE` is stopped, transitioning to `STOPPED` with its `stopped_at` set to the logical clock.

Cancelling a job is available from either `NOTICED` or `CONFIRMED` — the job's status must be one of those two states — and is performed by a `ScheduleCoordinator`. Cancellation moves the job to `CANCELLED`, cascades every `ACTIVE` assignment on the job to `RELEASED` (which frees each resource's time window for future overlap checks), recomputes the staffing posture down to `UNSTAFFED`, and increments `version`. Any state transition attempted from a status that does not define it — for example starting a job that is not `CONFIRMED`, or adjourning one that is not `IN_SESSION` — is rejected with `ERR_INVALID_STATE`.

### 3.6. Appearance Fees: Estimate Before, Actual After

The appearance fee a resource earns on a job is computed from the **actual** session duration once the job adjourns. Billable hours derive from the whole-minute span between `actual_start` and `actual_end`: take the elapsed time in whole minutes, divide by sixty, and round that quotient up to the next whole hour for any partial hour, then take whichever is larger of that figure and a two-hour minimum. In other words, every appearance is billed in whole hours with a floor of two hours, and any partial hour is rounded up. The base fee is the billable hours multiplied by the resource's `hourly_appearance_cents`. There is one surcharge: when the assignment's role is `REPORTER` and the job requires real-time, the base is increased by twenty percent — the base multiplied by 1.20, with that product rounded half up to the nearest cent. For every other assignment, the fee is the base unchanged. The resulting `appearance_fee_cents` is frozen onto each completed assignment at adjournment and is the authoritative billed value.

The same formula powers a provisional **estimate** that can be read before the job adjourns, for quoting purposes. The estimate differs in exactly one respect: it uses the **scheduled** window — the span between `scheduled_end` and `scheduled_start` — in place of the actual session times, while applying the identical two-hour minimum, round-up-to-whole-hour, and twenty-percent real-time-reporter surcharge rules. The appearance-estimate read returns an `estimated_total_cents` integer alongside `lines`, summing the estimated fees across only the job's `ACTIVE` assignments (released and completed assignments are excluded). `lines` is a JSON object that maps each contributing assignment's `id` to that assignment's estimated fee in cents (a bare integer), and `estimated_total_cents` is the sum of those line values.

### 3.7. Real-Time Streams

A job marked `requires_realtime` can carry a live transcript feed. A real-time **stream** is provisioned only while its job is `IN_SESSION` and `requires_realtime` is true, and only against a `reporter_assignment_id` that names an `ACTIVE` reporter assignment that belongs to that same job and whose underlying resource is `realtime_capable`; if any of these conditions is unmet, provisioning is rejected with `ERR_REALTIME_NOT_PROVISIONABLE` (the named `reporter_assignment_id` is first resolved for existence, so an unknown id yields `ERR_NOT_FOUND`). Provisioning creates the stream in `status` `STARTING` with its `access_token`, `started_at`, and `stopped_at` all unset. A stream's status is always one of `STARTING`, `LIVE`, or `STOPPED`.

Taking the stream live is a `Reporter` action that advances it from `STARTING` to `LIVE`. It requires the stream to be `STARTING`, the parent job to be `IN_SESSION`, and the referenced reporter assignment to still be `ACTIVE`, of role `REPORTER`, with a real-time-capable resource; a failure of any of these go-live preconditions is rejected with `ERR_INVALID_STATE`. Going live mints a fresh server-side `access_token` — an opaque feed token rotated only on a fresh start — and stamps `started_at` with the logical clock. Stopping a stream advances it from `LIVE` (or, defensively, from `STARTING`) to `STOPPED` and stamps `stopped_at` with the logical clock; an explicit stop may be performed by a `Reporter` or a `ScheduleCoordinator`, and a stop attempted from any status other than `LIVE` or `STARTING` (in practice, an already-`STOPPED` stream) is rejected with `ERR_INVALID_STATE`. A stream is also stopped automatically by the job-adjourn cascade of §3.5: a stream that was `LIVE` is stopped, and a stream that never went live — still `STARTING` when the job adjourns — is likewise driven to `STOPPED` with its `stopped_at` set to the clock. `STOPPED` is terminal.

### 3.8. Ordering and Producing the Transcript

After a job adjourns, a transcript may be ordered. A **transcript order** is created against the job by supplying `job_id`, the `ordering_attorney_id` (the party that pays the page rate), a `turnaround_tier`, and `estimated_pages`, and may also set `certified_copy`. The order is only valid when the referenced job's status is `ADJOURNED`; ordering against any other status is rejected with `ERR_JOB_NOT_ADJOURNED`. The `turnaround_tier` must be one of `STANDARD`, `EXPEDITE_14`, `EXPEDITE_7`, `EXPEDITE_3`, or `DAILY`, and drives the expedite multiplier on the page rate. The `estimated_pages` is the reporter's pre-production page estimate driving the provisional quote and must be zero or greater; a negative estimate is rejected with `ERR_INVALID_PAGE_COUNT`. The boolean `certified_copy` defaults to true and records whether a certified — rather than draft-only — transcript is ordered; a certified copy adds a flat fee and is what enables the read-and-sign process. A new order enters `status` `ORDERED` with `final_pages` null, `read_sign_deadline` null, and `errata_round` at 0. The full set of transcript statuses is `ORDERED`, `ROUGH_DELIVERED`, `CERTIFIED`, `READ_SIGN_OPEN`, `ERRATA_FILED`, `SIGNED`, `DELIVERED`, and `CANCELLED`.

Production proceeds in two reporter steps. A `Reporter` who covered the order's job — that is, who holds a `COMPLETED` reporter assignment on that job — first delivers the rough draft, advancing the order from `ORDERED` to `ROUGH_DELIVERED`. The same reporter then certifies, advancing from `ROUGH_DELIVERED` to `CERTIFIED`. This covering-reporter precondition is enforced on both steps: when the acting `Reporter` does not hold a `COMPLETED` reporter assignment on the order's job, the action is rejected with `ERR_FORBIDDEN_ROLE` (a `PlatformAdmin` acting in place of the reporter is exempt from this check). The covering-reporter check is evaluated after the status precondition for the step (so an order in the wrong status still yields `ERR_INVALID_STATE`). Certification is only available when `certified_copy` is true (certifying a draft-only order, where `certified_copy` is false, is rejected with `ERR_INVALID_STATE`, checked after the status and covering-reporter preconditions) and requires a supplied `final_pages` of at least 1; a final page count below 1 is rejected with `ERR_INVALID_PAGE_COUNT`. Certification records the supplied value into `final_pages` (the authoritative certified page count that drives final page-rate billing) and sets `read_sign_deadline` to thirty days after the current logical clock, opening the deponent's window to sign or file corrections.

An un-certified order may be cancelled by the ordering `Attorney` (or the case's noticing attorney) while it is still `ORDERED` or `ROUGH_DELIVERED`, moving it to `CANCELLED`; attempting to cancel from any later status is rejected as an invalid state transition. `DELIVERED` and `CANCELLED` are the terminal transcript states.

### 3.9. Exhibits

An **exhibit** is a document marked into a transcript. Any of an `Attorney`, a `ScheduleCoordinator`, or a `Reporter` may attach one by supplying a `marked_label` such as "Exhibit 1" or "Plaintiff-A", a `page_count`, and optionally a `confidential` flag. The label must be non-empty and unique within its transcript order; a repeat label on the same transcript is rejected with `ERR_DUPLICATE_EXHIBIT_LABEL`. The `page_count` is the number of pages in the exhibit and must be at least 1 — a value below 1 is rejected with `ERR_INVALID_REQUEST` — and these pages are billed at the exhibit per-page rate. The `confidential` flag defaults to false; when true the exhibit is sealed and excluded from the default e-delivery bundle, though — as detailed in §3.13 — confidential exhibits are still included in exhibit-charge billing. Each exhibit records the `transcript_order_id` of the transcript it attaches to. Exhibits have no lifecycle of their own.

### 3.10. The Read-and-Sign Cycle and Errata

Once a transcript is `CERTIFIED`, the deponent's party is given the opportunity to read it and either sign it or file corrections, and this read-and-sign process is deliberately cyclic so that multiple rounds of corrections can be exchanged before signature. A `ScheduleCoordinator` opens the window, transitioning the order from `CERTIFIED` to `READ_SIGN_OPEN`. While the window is open, an `Attorney` may file an **errata** sheet, which advances the order from `READ_SIGN_OPEN` to `ERRATA_FILED`. Filing errata requires the acting attorney to be a case party — either the order's `ordering_attorney_id` or the job's case `noticing_attorney_id`, failing which the action is rejected with `ERR_NOT_CASE_PARTY`; this case-party check is evaluated before the state and window checks (so a non-case-party acting on a wrong-status order still sees `ERR_NOT_CASE_PARTY`). It then requires the order to be `READ_SIGN_OPEN` (otherwise `ERR_INVALID_STATE`), and requires the logical clock to be strictly before the `read_sign_deadline` (an errata filed at or after the deadline is rejected with `ERR_READ_SIGN_WINDOW_CLOSED`). The same case-party-before-state precedence governs the sign and cancel actions.

An errata sheet is supplied with a non-empty `corrections` array — a list of correction objects each carrying a `page`, a `line`, a `from_text`, and a `to_text` — and a non-empty `reason` stating why the corrections are made, which most jurisdictions require. An empty corrections array is rejected with `ERR_INVALID_PAGE_COUNT`. Filing creates the errata sheet, stamping its `round` to the transcript's current `errata_round` plus one, increments the transcript's `errata_round` by one, and moves the order to `ERRATA_FILED`. To exchange another round, the `ScheduleCoordinator` re-opens the window, transitioning the order back from `ERRATA_FILED` to `READ_SIGN_OPEN` and leaving the deadline unchanged; this loop may repeat and is bounded by the `read_sign_deadline` rather than by any fixed round count.

When the deponent's party is satisfied, an `Attorney` who is a case party signs, advancing a `READ_SIGN_OPEN` order to `SIGNED` (a non-case-party signer is rejected with `ERR_NOT_CASE_PARTY`). Signature may also be reached without an explicit sign action: if the read-and-sign window lapses, the deponent's signature is deemed waived. After the logical clock has advanced to or past the `read_sign_deadline`, a `ScheduleCoordinator` may finalize the deadline, which auto-waives the signature and moves the order to `SIGNED`. This deadline-finalization is permitted from `CERTIFIED`, `READ_SIGN_OPEN`, or `ERRATA_FILED` (the order's status must be one of those three) and requires that the `read_sign_deadline` be set and that the logical clock be at or past it; a failure of either precondition (wrong status, or the deadline unset or not yet reached) is rejected with `ERR_INVALID_STATE`. Finally, a `ScheduleCoordinator` e-delivers a `SIGNED` transcript, advancing it from `SIGNED` to `DELIVERED` and making the e-delivery bundle available to the ordering attorney. As with jobs and invoices, any transcript-order transition (open-read-sign, sign, deliver, and the like) attempted from a status that does not define it is rejected with `ERR_INVALID_STATE`.

### 3.11. Provisional Quotes vs. Final Page Charges

The page-rate charge for a transcript is a tiered, jurisdiction-driven, expedite-adjusted figure, and it is offered first as a provisional **quote** and later frozen as the **final billed** value. Both use the same logic; they differ only in the page count fed in — the quote uses the order's `estimated_pages`, while the final charge uses the `final_pages` set at certification.

The base per-page rate is selected by the case jurisdiction: 380 cents for `FEDERAL`, 325 cents for `STATE_CA`, 400 cents for `STATE_NY`, and 300 cents for `STATE_TX`. Pages are then priced on a marginal tier ladder, not an average rate. The first 50 pages are charged at the full base rate. Pages 51 through 150 are charged at the base rate reduced by ten percent — that is, the base rate multiplied by 0.90 and rounded half up to a whole cent, applied per page in that band. Pages beyond 150 are charged at the base rate reduced by twenty percent — the base rate multiplied by 0.80 and rounded half up to a whole cent, per page. Concretely, the first tier covers up to 50 pages, the second tier covers the count of pages above 50 up to 150 (zero if there are 50 or fewer), and the third tier covers the count of pages above 150 (zero if there are 150 or fewer). The per-tier marginal rate is rounded to a whole cent **before** it is multiplied by that tier's page count, and the three tier products are then summed to form the page base.

The expedite multiplier is applied **after** the tier sum, in this pinned order: multiply the summed page base by the multiplier for the order's turnaround tier — 1.00 for `STANDARD`, 1.25 for `EXPEDITE_14`, 1.50 for `EXPEDITE_7`, 2.00 for `EXPEDITE_3`, and 3.00 for `DAILY` — and round the result half up to a whole cent. Last, and only if the order is a certified copy, a flat certification fee of 2500 cents is **added after** the multiplier (it is not multiplied by the expedite factor). The resulting amount is the page charge — the provisional `provisional_page_cents` when computed from estimated pages at quote time, or the `page_subtotal_cents` of the invoice when computed from final pages at issue time.

### 3.12. The Quote Read

The provisional quote read returns two figures for a transcript order: a `provisional_page_cents` computed by the §3.11 logic from `estimated_pages`, and an `exhibit_cents` reflecting the exhibit charge described in §3.13. It is a pure read with no side effects and is available to attorneys, coordinators, and billing.

### 3.13. Exhibit Charges

The exhibit charge is a straightforward aggregate. Sum the `page_count` across **all** exhibits attached to the transcript order — there is no status filter and, importantly, confidential exhibits are included in this billing total even though they are withheld from the default e-delivery bundle — and multiply that total page count by the exhibit per-page rate of 75 cents in a single multiplication with no intermediate rounding. The result is the transcript's `exhibit_subtotal_cents`.

### 3.14. Invoicing and Reconciliation

Billing is the province of the `BillingClerk`. An **invoice** links one job and one transcript order, settling the job's appearance fees together with the transcript's page and exhibit charges. The clerk creates a draft invoice by supplying `job_id`, `transcript_order_id`, and optionally `bill_to_attorney_id`; when the billed party is omitted it defaults to the transcript's ordering attorney. A new invoice enters `status` `DRAFT` with its three subtotals — `appearance_subtotal_cents`, `page_subtotal_cents`, and `exhibit_subtotal_cents` — and its reconciled `total_cents` all computed as a preview from current state and defaulting to 0. The invoice statuses are `DRAFT`, `ISSUED`, `PAID`, and `VOID`.

Issuing the invoice freezes its numbers. Issuance is permitted only from `DRAFT` and additionally requires that the linked transcript order's status is `DELIVERED` and that the recomputed `total_cents` is greater than 0; if the transcript is not yet delivered or the total would be zero, the issue is rejected with `ERR_INVOICE_NOT_READY`. On issue, all three subtotals and the grand total are recomputed and frozen from current job, transcript, and exhibit state, and the status moves to `ISSUED`. The `appearance_subtotal_cents` is the sum of `appearance_fee_cents` across the job's `COMPLETED` assignments. The `page_subtotal_cents` is the §3.11 page charge computed from the transcript's `final_pages`. The `exhibit_subtotal_cents` is the §3.13 exhibit aggregate. The reconciled `total_cents` is the plain sum of the three already-rounded subtotals — appearance plus page plus exhibit — with no further rounding.

An `ISSUED` invoice can be marked paid, advancing it to `PAID`. An invoice can also be voided from either `DRAFT` or `ISSUED` (its status must be one of those two), moving it to `VOID`. `PAID` and `VOID` are terminal. Any invoice transition attempted from a status that does not define it is rejected with `ERR_INVALID_STATE`.

### 3.15. Cross-Cutting Validation Notes

A handful of validations apply broadly. Every create and update endpoint requires its mandatory body fields to be present and well-typed, with enum-valued fields restricted to their declared sets; a missing required field, a malformed type, or an out-of-set enum value is rejected with `ERR_INVALID_REQUEST`. Existence of every path identifier and every foreign-key body field is enforced as described in §2.5, yielding `ERR_NOT_FOUND`. The uniqueness constraints — docket number across cases and email across attorneys — yield `ERR_DUPLICATE_KEY`. Beyond the specific business errors named throughout §3, a generic business-rule violation that no more specific 422 covers is reported as `ERR_VALIDATION`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return a `201 Created`. Operations that modify an existing resource — including all the lifecycle-transition actions and the computed reads — return a `200 OK`. The table below lists every endpoint; request and response payloads are described in the §3 workflow narratives rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cases` | Create a case file | ScheduleCoordinator, PlatformAdmin |
| GET | `/cases/{id}` | Fetch a case | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| GET | `/cases` | List cases; filter by noticing attorney | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| GET | `/cases/{id}/jobs` | List jobs under a case | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| POST | `/attorneys` | Register an attorney party | ScheduleCoordinator, PlatformAdmin |
| GET | `/attorneys/{id}` | Fetch an attorney | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| GET | `/attorneys` | List attorneys; filter by email | ScheduleCoordinator, BillingClerk, PlatformAdmin |
| POST | `/resources` | Register a reporter / videographer / interpreter | ScheduleCoordinator, PlatformAdmin |
| GET | `/resources/{id}` | Fetch a resource | ScheduleCoordinator, BillingClerk, PlatformAdmin |
| GET | `/resources` | List resources; filter by kind | ScheduleCoordinator, BillingClerk, PlatformAdmin |
| POST | `/resources/{id}/deactivate` | Mark a resource inactive | PlatformAdmin |
| GET | `/resources/{id}/assignments` | List assignments for a resource; filter by status | ScheduleCoordinator, BillingClerk, PlatformAdmin |
| POST | `/jobs` | Notice a deposition job | ScheduleCoordinator, PlatformAdmin |
| GET | `/jobs/{id}` | Fetch a job with derived staffing posture | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| GET | `/jobs` | List jobs; filter by case and status | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| POST | `/jobs/{id}/assignments` | Assign a resource to a job (OCC-guarded) | ScheduleCoordinator, PlatformAdmin |
| GET | `/jobs/{id}/assignments` | List assignments on a job; filter by status | ScheduleCoordinator, BillingClerk, Attorney, PlatformAdmin |
| POST | `/jobs/{id}/confirm` | Confirm a fully-staffed job | ScheduleCoordinator, PlatformAdmin |
| POST | `/jobs/{id}/start` | Open the deposition session | ScheduleCoordinator, PlatformAdmin |
| POST | `/jobs/{id}/adjourn` | Close the session; complete assignments and compute fees | ScheduleCoordinator, PlatformAdmin |
| POST | `/jobs/{id}/cancel` | Cancel a job; release active assignments | ScheduleCoordinator, PlatformAdmin |
| GET | `/jobs/{id}/appearance-estimate` | Provisional appearance fees using scheduled times | ScheduleCoordinator, BillingClerk, PlatformAdmin |
| GET | `/assignments/{id}` | Fetch an assignment | ScheduleCoordinator, BillingClerk, PlatformAdmin |
| POST | `/assignments/{id}/release` | Release an active assignment | ScheduleCoordinator, PlatformAdmin |
| POST | `/jobs/{id}/realtime-streams` | Provision a realtime stream | ScheduleCoordinator, Reporter, PlatformAdmin |
| GET | `/jobs/{id}/realtime-streams` | List realtime streams on a job; filter by status | ScheduleCoordinator, Reporter, BillingClerk, Attorney, PlatformAdmin |
| GET | `/realtime-streams/{id}` | Fetch a realtime stream | ScheduleCoordinator, Reporter, BillingClerk, Attorney, PlatformAdmin |
| GET | `/realtime-streams` | List realtime streams; filter by job, reporter assignment, and status | ScheduleCoordinator, Reporter, BillingClerk, PlatformAdmin |
| POST | `/realtime-streams/{id}/go-live` | Take a provisioned stream live | Reporter, PlatformAdmin |
| POST | `/realtime-streams/{id}/stop` | Stop a live stream | Reporter, ScheduleCoordinator, PlatformAdmin |
| POST | `/transcript-orders` | Order a transcript for an adjourned job | Attorney, ScheduleCoordinator, PlatformAdmin |
| GET | `/transcript-orders/{id}` | Fetch a transcript order | Attorney, ScheduleCoordinator, BillingClerk, Reporter, PlatformAdmin |
| GET | `/transcript-orders` | List transcript orders; filter by job, ordering attorney, and status | Attorney, ScheduleCoordinator, BillingClerk, PlatformAdmin |
| GET | `/transcript-orders/{id}/quote` | Provisional page-charge quote using estimated pages | Attorney, ScheduleCoordinator, BillingClerk, PlatformAdmin |
| POST | `/transcript-orders/{id}/deliver-rough` | Reporter delivers the rough draft | Reporter, PlatformAdmin |
| POST | `/transcript-orders/{id}/certify` | Reporter certifies; sets final pages and read-sign deadline | Reporter, PlatformAdmin |
| POST | `/transcript-orders/{id}/open-read-sign` | Open or re-open the read-and-sign window | ScheduleCoordinator, PlatformAdmin |
| POST | `/transcript-orders/{id}/errata` | File an errata sheet (cyclic) | Attorney, PlatformAdmin |
| POST | `/transcript-orders/{id}/sign` | Sign the transcript | Attorney, PlatformAdmin |
| POST | `/transcript-orders/{id}/finalize-deadline` | Auto-waive signature after deadline lapse | ScheduleCoordinator, PlatformAdmin |
| POST | `/transcript-orders/{id}/deliver` | E-deliver the signed transcript bundle | ScheduleCoordinator, PlatformAdmin |
| POST | `/transcript-orders/{id}/cancel` | Cancel an un-certified transcript order | Attorney, PlatformAdmin |
| POST | `/transcript-orders/{id}/exhibits` | Attach an exhibit to a transcript | Attorney, ScheduleCoordinator, Reporter, PlatformAdmin |
| GET | `/transcript-orders/{id}/exhibits` | List exhibits on a transcript; filter by confidential | Attorney, ScheduleCoordinator, BillingClerk, Reporter, PlatformAdmin |
| GET | `/exhibits/{id}` | Fetch an exhibit | Attorney, ScheduleCoordinator, BillingClerk, Reporter, PlatformAdmin |
| GET | `/transcript-orders/{id}/errata` | List errata sheets on a transcript | Attorney, ScheduleCoordinator, BillingClerk, Reporter, PlatformAdmin |
| GET | `/errata/{id}` | Fetch an errata sheet | Attorney, ScheduleCoordinator, BillingClerk, PlatformAdmin |
| POST | `/invoices` | Create a draft invoice linking a job and its transcript | BillingClerk, PlatformAdmin |
| GET | `/invoices/{id}` | Fetch an invoice | BillingClerk, Attorney, PlatformAdmin |
| GET | `/invoices` | List invoices; filter by job, transcript, bill-to attorney, and status | BillingClerk, Attorney, PlatformAdmin |
| POST | `/invoices/{id}/issue` | Freeze and issue the invoice | BillingClerk, PlatformAdmin |
| POST | `/invoices/{id}/pay` | Mark an issued invoice paid | BillingClerk, PlatformAdmin |
| POST | `/invoices/{id}/void` | Void a draft or issued invoice | BillingClerk, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_CASE_PARTY` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_ROLE_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RESOURCE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_ROLE_ALREADY_FILLED` | 422 Unprocessable Entity |
| `ERR_INTERPRETER_LANGUAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REALTIME_NOT_CAPABLE` | 422 Unprocessable Entity |
| `ERR_RESOURCE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_REPORTER_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_JOB_NOT_ADJOURNED` | 422 Unprocessable Entity |
| `ERR_INVALID_PAGE_COUNT` | 422 Unprocessable Entity |
| `ERR_READ_SIGN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_EXHIBIT_LABEL` | 409 Conflict |
| `ERR_INVOICE_NOT_READY` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REALTIME_NOT_PROVISIONABLE` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
</content>
</invoke>
