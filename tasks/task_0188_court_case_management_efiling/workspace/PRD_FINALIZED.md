# Court Case Management & e-Filing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Court Case Management & e-Filing API, a back-office platform for the civil docket of a trial court. The system carries a civil matter from its first paperwork through final disposition: clerks open a docket and mint a case number, attorneys e-file complaints and motions, service of process is recorded against named defendants, statutory and procedural deadlines are calendared, judges hold hearings and rule on motions, judgments are entered and accrue post-judgment interest, fee waivers are adjudicated for indigent litigants, and appeals are noticed and transmitted to the appellate court.

Three concerns dominate the design. First, **correct calendaring**: civil deadlines obey two distinct counting variants — pure calendar days and court days — and both must roll over weekends and court holidays exactly as a clerk would. Second, **case posture as a gate**: a case is not merely OPEN or CLOSED; its derived posture (whether it is `ACTIVE`, `RESTRICTED`, or `FROZEN`) governs which child operations are even permitted, and that posture is recomputed continuously as deadlines, motions, and judgments come and go. Third, **auditability under concurrency**: because several officers act on the same docket, the entry of a judgment or the filing of an appeal is guarded against stale views of the case so that no actor overwrites a transition they never observed. The remainder of this document defines the system-wide contract (Section 2), the business workflows where the bulk of the domain rules live (Section 3), the endpoint surface (Section 4), and the catalogue of error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the rules, envelope, and cross-cutting principles that apply uniformly across the API. All resources are mounted directly under the root path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The role value must be exactly one of `Clerk`, `Judge`, `Attorney`, or `SystemAdmin`. If either header is missing, or `X-User-Role` is not one of these four values, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`.

The four roles are peers, each owning a distinct slice of the docket. A `Clerk` performs docketing (opening, closing, and number assignment), reviews and accepts or rejects filings, processes fees, records service of process, calendars and manages deadlines, decides fee waivers, and prepares and transmits the record on appeal. A `Judge` takes motions under submission and rules on them, schedules and manages hearings, enters and vacates judgments, lifts stays, vacates deadlines, and dismisses appeals. An `Attorney` is counsel of record for a party: they e-file documents, file and withdraw motions, request and resubmit fee waivers, and file notices of appeal. A `SystemAdmin` is the platform operator who configures courts and drives the system clock.

For the three court-officer roles — `Clerk`, `Judge`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow captures it (for example, a `judge_user_id` stored on a `Hearing`), but it does not compare it to any entity's `id`. The `Attorney` role is different: it is entity-backed by the `Party` record. When `X-User-Role` is `Attorney`, `X-User-ID` is the opaque attorney identifier that appears as `attorney_user_id` on the parties that attorney represents; ownership checks on any resource that references a `Party` compare that party's `attorney_user_id` to `X-User-ID`. Concretely, an attorney may only withdraw a motion whose moving party they represent — a mismatch is rejected with `ERR_NOT_MOVING_PARTY` — and may only resubmit a fee waiver whose requesting party they represent, a mismatch being rejected with `ERR_NOT_REQUESTING_PARTY`.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip from the front of the result set and defaults to 0. Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp, `created_at`, in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every resource the API persists carries a server-minted `id` rendered as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are also mutable and therefore additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every change) and an integer `version` that begins at 1 on creation and increments by one on each mutation. Updates to derived fields — for example recomputing a case's posture or fee aggregates — are themselves mutations: they refresh `updated_at` and increment `version` on the resource that changed. Most lifecycle-bearing resources additionally expose a `status` field whose permissible values and transitions are defined per entity in Section 3, and which may also be supplied as a `status` filter on the corresponding list endpoints.

A case is identified to the outside world by its `case_number`. This is a server-minted civil docket number and is never supplied by the client. Its format is the court's two-letter jurisdiction code, then a four-digit year, then the literal segment `CV`, then a six-digit sequence, joined by hyphens — for example `CA-2026-CV-000123`. The six-digit sequence is zero-padded and counts cases per court and per calendar year: the year is taken from the system clock at the moment the case is created, and the sequence is one greater than the number of existing cases already minted for the same court in that same year. Ordering for this count is by `created_at` ascending, ties broken by `created_at` then by insertion order, and never by `id`. The first case for a given court in a given year therefore receives sequence `000001`.

### 2.5. Nested Reference Validation and Existence Checks

Resources in this system are peers that reference their owners by foreign key rather than by deep URL nesting, so reverse navigation is provided through filtered list endpoints (for example, listing motions for a given case). For any request, the system validates the existence of every path identifier and every foreign-key-referenced resource before applying business rules, and it does so left to right: a request that names a case, a filing, and a party resolves them in that order and is rejected at the first identifier that does not correspond to an existing resource. Any such failure yields `ERR_NOT_FOUND`.

Beyond mere existence, foreign keys must point within the same case as the operation being performed. A motion's `moving_party_id` must be a party of the motion's `case_id`; a service-of-process record's `served_party_id` must be a `DEFENDANT` party of the same case; and analogous same-case constraints apply to the references carried by orders, fee waivers, appeals, and hearings. A foreign key that resolves to a resource belonging to a different case, or to a party with the wrong role, is rejected with `ERR_CROSS_CASE_REFERENCE`. This cross-case referential check applies specifically when filing a motion, recording service of process, creating an order, requesting a fee waiver, filing an appeal, and scheduling a hearing.

### 2.6. The System Clock

Calendaring, interest accrual, deadline-due checks, and appeal-window checks are all evaluated against a single logical system clock rather than wall-clock time. An administrative capability lets a `SystemAdmin` set the current UTC instant by supplying a `to_iso8601` value; the response echoes the new clock as `current_utc`. Every subsequent time-relative computation — due-date calculation, post-judgment interest, whether a deadline is past due, whether an appeal window is still open — reads this clock.

### 2.7. Case Posture and Operational Gating

Each case carries a derived `posture` field with one of three values — `ACTIVE`, `RESTRICTED`, or `FROZEN` — recomputed on every transition that changes the case's deadlines, motions, judgments, or status. Posture is computed as follows. If the case status is `STAYED`, the posture is `FROZEN`. Otherwise, if the case has at least one deadline in status `MISSED`, or the number of its deadlines in status `PENDING` is five or more, the posture is `RESTRICTED`. In all other cases the posture is `ACTIVE`. The count that drives the `RESTRICTED` threshold is the case's `open_deadline_count`, an integer that tracks the number of `PENDING` deadlines under the case and is incremented when a pending deadline is created and decremented whenever a deadline leaves `PENDING`.

Posture is a gate. A `FROZEN` posture blocks both filing acceptance and motion rulings; an attempt at either while frozen is rejected with `ERR_CASE_FROZEN`. A `RESTRICTED` posture blocks the filing of a new motion — rejected with `ERR_CASE_RESTRICTED` — but still permits deadline-satisfying filings to proceed, so that a litigant can cure an overdue obligation even while the case is restricted.

### 2.8. Monetary Values, Counts, and Precision

Monetary amounts are carried as integer cents throughout, and counts are exact integers. Where a calculation produces a fractional cent — post-judgment interest is the principal case — the result is rounded to whole cents using the round-half-up convention. The fee-waiver eligibility ratio is the one non-integer stored value: it is rounded half up to four decimal places. The appeal transmittal fee is computed in whole cents from marginal per-tier rates and is never averaged. Section 3 states each formula in full.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded against stale views of a case, because each legitimately advances the case to a new posture or status that a concurrent writer may not have observed. Both guards key on the case's current `version` and use the request field `expected_case_version`.

Entering a judgment requires the request to carry `expected_case_version` matching the target case's current `version`. If another writer has advanced the case's version since the client last read it — for instance by ruling a final motion or recomputing posture — the create is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing entry of a judgment against a case the client has not observed in its current state. Filing a notice of appeal carries the same requirement: the request must supply `expected_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412, since the new appeal supersedes the prior case view by driving the case to `ON_APPEAL`. No other endpoint takes a version field; only judgment entry and appeal filing are OCC-guarded.

### 2.10. Cascading Consistency and Validation Ordering

Many operations in this domain touch more than one resource. When that happens, the system applies every cascade described in Section 3, refreshing `updated_at` and incrementing `version` on each resource it mutates — most often the child resource that changed and the owning case, whose posture and aggregates it recomputes. The deepest of these chains run three hops (completing service of process serves the party, creates a response deadline, and recomputes case posture), and Section 3 enumerates each one.

Validation is evaluated in a fixed priority order so that the most fundamental failures surface first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of all path and foreign-key resources (`ERR_NOT_FOUND`), then request-body well-formedness (`ERR_INVALID_REQUEST`), then same-case referential integrity (`ERR_CROSS_CASE_REFERENCE`), then the optimistic-concurrency version check on guarded writes (`ERR_STALE_VERSION`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Domain safety and business gates are evaluated only after all of the foregoing pass: the frozen-case gate (`ERR_CASE_FROZEN`), the restricted-case gate (`ERR_CASE_RESTRICTED`), hearing-conflict checks (`ERR_HEARING_CONFLICT`), the statute-of-limitations bar (`ERR_STATUTE_EXPIRED`), the unpaid-fee bar (`ERR_FILING_FEE_UNPAID`), and the appeal-window check (`ERR_APPEAL_WINDOW_CLOSED`). Request-body well-formedness under `ERR_INVALID_REQUEST` covers the presence of required fields, valid enum values, non-negative numbers, and the rule that any `end_at` strictly exceeds its corresponding `start_at`.

## 3. Business Logic & Workflows

### 3.1. Court Configuration and Docket Opening

A `SystemAdmin` configures each court before any case is filed against it. A court is created with a `name`, a two-letter `jurisdiction_code`, and a standard civil-complaint `filing_fee_cents` that must be zero or greater. Three further settings govern calendaring and appeals: `business_days_only`, a boolean defaulting to true that, when set, causes deadline calendaring to roll dates forward over weekends and holidays; `holidays`, an array of `YYYY-MM-DD` date strings that the court observes, defaulting to an empty array; and `appeal_window_days`, the number of calendar days after a judgment is entered within which an appeal may be filed, defaulting to 30.

A `Clerk` opens a docket by creating a case under a court, supplying the `court_id`, the case `caption`, and the `case_type`, which must be one of `CONTRACT`, `TORT`, `PROPERTY`, or `FAMILY`. The new case is created in status `DRAFT` with posture `ACTIVE`, and its `case_number` is minted at creation as described in Section 2.4. A case read exposes, alongside its stored fields, the derived `posture`, the `open_deadline_count`, and two fee aggregates: `total_fees_assessed_cents`, the sum of `fee_cents` over the case's accepted filings whose `fee_status` is `ASSESSED` or `PAID`, and `total_fees_paid_cents`, the sum of `fee_cents` over the case's filings whose `fee_status` is `PAID` or `WAIVED`.

Before a draft case can be opened to active litigation, two preconditions must hold. There must be at least one `PLAINTIFF` party and at least one `DEFENDANT` party on the case, failing which the open is rejected with `ERR_CASE_MISSING_PARTIES`; and there must be at least one `ACCEPTED` filing whose `document_type` is `COMPLAINT`, failing which it is rejected with `ERR_NO_ACCEPTED_COMPLAINT`. When a `Clerk` opens the case, it transitions `DRAFT → OPEN`, a statute-of-limitations deadline is created for the case (a `STATUTE_OF_LIMITATIONS` deadline anchored on the case-opened event, in status `PENDING`), posture is recomputed, and the case's `version` increments by one.

Closing a case is also a clerk action, and the case must already be at the end of its life. A case in `JUDGMENT_ENTERED` may be closed only if no `APPEAL`-type deadline under it is still `PENDING` with a `due_date` at or after the current clock; if such a live appeal deadline exists, the close is rejected with `ERR_APPEAL_WINDOW_OPEN`. A case in `ON_APPEAL` may be closed only if every appeal on the case is in status `TRANSMITTED` or `DISMISSED`; otherwise the close is rejected with `ERR_APPEAL_NOT_TRANSMITTED`. On either path the case transitions to `CLOSED`, every deadline under the case still in `PENDING` is moved to `VACATED`, and the case `version` increments. `CLOSED` is terminal.

### 3.2. Parties and the e-Filing Review Cycle

A `Clerk` adds parties to a case by supplying the `case_id`, the party's `display_name`, its `role` (one of `PLAINTIFF` or `DEFENDANT`), and the `attorney_user_id` of the attorney who represents that party. A defendant party begins with a `service_status` of `UNSERVED`; this field, together with the `served_at` timestamp, is only meaningful for defendants, and can later read `SERVED` or `SERVICE_FAILED`.

Attorneys e-file documents into a case. A filing carries its `case_id`, the `filed_by_party_id` of the party filing it, a `document_type` — one of `COMPLAINT`, `ANSWER`, `MOTION`, `EXHIBIT`, or `PROOF_OF_SERVICE` — and a `title`. On creation the filing enters status `SUBMITTED`. Its `fee_cents` is computed at this point: a `COMPLAINT` is charged the owning court's `filing_fee_cents`, and every other document type is charged zero. The `fee_status` follows from that amount — `ASSESSED` when `fee_cents` is greater than zero, and `NONE` when `fee_cents` is zero. A filing also carries a nullable `rejection_reason` (set only on rejection), an `accepted_at` timestamp (null until accepted), and an optional `resubmits_filing_id` linking it to a previously rejected filing it replaces.

A clerk works a filing through review. From `SUBMITTED`, claiming a filing for review advances it `SUBMITTED → UNDER_REVIEW`. From `UNDER_REVIEW` the clerk may accept or reject it. Accepting requires that the owning case's posture is not `FROZEN` (else `ERR_CASE_FROZEN`) and, when the document is a `COMPLAINT` with a positive `fee_cents`, that its `fee_status` is `PAID` or `WAIVED` rather than still `ASSESSED` (else `ERR_FILING_FEE_UNPAID`). A further bar applies to complaints: a `COMPLAINT` filing cannot be accepted once the case's `STATUTE_OF_LIMITATIONS` deadline `due_date` has passed relative to the current clock; such an attempt is rejected with `ERR_STATUTE_EXPIRED`. Acceptance moves the filing `UNDER_REVIEW → ACCEPTED`, sets `accepted_at` to the current clock, and — when the document is a complaint — recomputes the case's `total_fees_assessed_cents` and `total_fees_paid_cents` aggregates; a fee that was already `PAID` or `WAIVED` is left as it stands. Acceptance is also the moment a resubmission can satisfy a deadline: if the accepted filing carries a `resubmits_filing_id` and that lineage maps to a deadline that is `MISSED` or `PENDING`, that deadline is moved to `SATISFIED` and its `satisfied_by_filing_id` is set. Acceptance increments both the filing's `version` and the case's `version`.

Rejecting a filing requires a `rejection_reason` to be supplied; without one the rejection is refused with `ERR_REJECTION_REASON_REQUIRED`. Rejection moves the filing `UNDER_REVIEW → REJECTED`, records the `rejection_reason`, and — if the filing's `fee_status` was `ASSESSED` — releases that fee by setting `fee_status` back to `NONE` and recomputing the case fee aggregates, incrementing the filing's `version`. Both `ACCEPTED` and `REJECTED` are terminal for that filing row. A rejected filing is cured not by reopening it but by submitting a new filing whose `resubmits_filing_id` points at it: the attorney files afresh, the new row is created in `SUBMITTED`, the referenced rejected filing stays `REJECTED`, and the two are linked. The resubmission target must itself be in status `REJECTED`; pointing `resubmits_filing_id` at a filing in any other state is rejected with `ERR_RESUBMIT_TARGET_NOT_REJECTED`.

Filing fees are settled separately from review. An assessed fee can be paid — by either the filing attorney or a clerk — which moves `fee_status` from `ASSESSED` to `PAID` and recomputes the case's `total_fees_paid_cents`.

### 3.3. Service of Process

Service of process records the delivery of the complaint to a defendant. A `Clerk` records an attempt by supplying the `case_id`, the `filing_id` of the complaint whose service this records, the `served_party_id` of the defendant being served, the `method` (one of `PERSONAL`, `MAIL`, or `PUBLICATION`), and the `service_date`. The record begins in status `ATTEMPTED`. A nullable `response_due_deadline_id` links the record to the responsive-pleading deadline that completion will create.

Completing service is the depth-three cascade at the heart of the early-case timeline, and it carries three preconditions: the record must be `ATTEMPTED`, the owning case must be `OPEN` (else `ERR_CASE_NOT_OPEN`), and the `served_party_id` must refer to a `DEFENDANT` party whose `service_status` is not already `SERVED` (else `ERR_PARTY_ALREADY_SERVED`). On completion, the record transitions `ATTEMPTED → COMPLETED` and three things follow in sequence: the served party's `service_status` becomes `SERVED` and its `served_at` is set (hop one); a responsive-pleading deadline is created — a `RESPONSE` deadline anchored on the service-completed event, with its `anchor_date` taken from the `service_date`, counted in court days over an interval of thirty days, in status `PENDING` — its id recorded as the record's `response_due_deadline_id`, which increments the case's `open_deadline_count` (hop two); and the case posture is recomputed, since the new pending deadline may flip the posture to `RESTRICTED` (hop three). Completion increments the service record's `version` and the case's `version`.

Recording a failed service is the simpler branch: from `ATTEMPTED` it transitions to `FAILED`, the served party's `service_status` becomes `SERVICE_FAILED`, and the service record's `version` increments. No deadline is created and no case-level recompute occurs on this branch.

### 3.4. Deadlines and the Calendaring Engine

Deadlines are the calendar of the case. A deadline carries its `case_id`, a `deadline_type` (one of `RESPONSE`, `DISCOVERY`, `MOTION_HEARING`, `STATUTE_OF_LIMITATIONS`, or `APPEAL`), an `anchor_event` naming the event that starts the count (`SERVICE_COMPLETED`, `FILING_ACCEPTED`, `JUDGMENT_ENTERED`, `CASE_OPENED`, or `MANUAL`), an `anchor_date` giving the date that event occurred, an `interval_days` count of zero or more days to add, and a `counting_mode` choosing the calendaring variant. It also carries an optional self-referential `parent_deadline_id` that chains a derived deadline (such as an appeal window) back to the deadline or event that anchors it, and a `satisfied_by_filing_id` set when a filing satisfies it. The computed `due_date` is pinned to 23:59:59.000Z of the landing day.

The due-date calculation has two variants, both of which begin counting the day **after** the `anchor_date`. Under the calendar variant, selected when `counting_mode` is `CALENDAR`, the engine first adds the full `interval_days` as calendar days to the anchor date. If the court runs business-days-only and that landing day falls on a Saturday, a Sunday, or one of the court's `holidays`, the date rolls forward one day at a time to the next court day; the rolled-over days are not re-counted. Under the court-day variant, selected when `counting_mode` is `COURT_DAYS`, the engine instead steps forward one day at a time from the day after the anchor date and counts only court days: any day that is a Saturday, Sunday, or court holiday is skipped without consuming any of the interval, and stepping stops once `interval_days` court days have been counted, so the landing day is always itself a court day. Because weekends and holidays consume none of the interval in the court-day variant, the same `interval_days` yields a later calendar date than the calendar variant would. In both variants, weekends are Saturday and Sunday, and the rolling/skipping behavior over weekends and holidays is active only when the court's `business_days_only` is true.

A deadline begins `PENDING`. It leaves that state by one of three routes. It may be satisfied — either automatically when a filing mapped to it is accepted, or manually by a clerk — moving `PENDING → SATISFIED`; on a filing-driven satisfaction the `satisfied_by_filing_id` is set, and in either case the case's `open_deadline_count` decrements by one, posture is recomputed, and both the deadline's and the case's `version` increment. It may be marked missed by a clerk, but only once the current clock is strictly past its `due_date`; an attempt before then is rejected with `ERR_DEADLINE_NOT_YET_DUE`. Marking missed moves `PENDING → MISSED`, decrements `open_deadline_count`, and recomputes posture — and because any missed deadline forces `RESTRICTED`, a missed response deadline can push the case into the restricted posture; both versions increment. Finally a deadline may be vacated — by a judge directly, or by a system cascade when the case is stayed or closed — moving `PENDING → VACATED`, decrementing `open_deadline_count`, recomputing posture, and incrementing both versions. `SATISFIED`, `MISSED`, and `VACATED` are terminal.

### 3.5. Motions, Hearings, and Orders

A motion is brought by an attorney on an accepted motion-type filing. Filing a motion supplies the `case_id`, the `filing_id` of the accepted `MOTION`-type filing that introduced it, the `moving_party_id` of the party bringing it, the `motion_type` (one of `DISMISS`, `SUMMARY_JUDGMENT`, `CONTINUANCE`, or `COMPEL_DISCOVERY`), and an optional `opposed` flag defaulting to false. New motions are barred while the case posture is `RESTRICTED`, rejected with `ERR_CASE_RESTRICTED`; an accepted motion otherwise begins in status `FILED`. A motion also carries a `hearing_id` (null until a hearing is scheduled to decide it) and an `order_id` (null until it is ruled on).

Hearings are scheduled by a judge. A hearing carries its `case_id`, an optional `motion_id` (the motion to be heard, null for a general case hearing), a `courtroom` identifier, the presiding `judge_user_id`, and a `start_at` and `end_at` where the end must be strictly after the start. When a hearing names a motion, that motion's `hearing_id` is linked to it. Scheduling enforces a temporal non-overlap rule on two axes: the proposed window must not overlap an existing `SCHEDULED` hearing in the same `courtroom`, and must not overlap an existing `SCHEDULED` hearing for the same `judge_user_id`. A violation on either axis is rejected with `ERR_HEARING_CONFLICT`. A hearing begins `SCHEDULED`.

Holding a hearing is allowed only once the current clock is at or after its `start_at`; an earlier attempt is rejected with `ERR_HEARING_NOT_STARTED`. Holding moves the hearing `SCHEDULED → HELD`, and if the hearing names a motion still in status `FILED`, that motion is advanced `FILED → UNDER_SUBMISSION` as a cascade; the hearing's `version` increments. Continuing a hearing reschedules it: the judge supplies a `new_start_at` and `new_end_at`, which must be free of the same courtroom and judge overlap (else `ERR_HEARING_CONFLICT`); a brand-new hearing row is created `SCHEDULED` at the new window carrying the same `motion_id`, the original hearing transitions `SCHEDULED → CONTINUED`, and the original's `version` increments. Cancelling a hearing — directly by a judge, or as a cascade when its linked motion is withdrawn — moves it `SCHEDULED → CANCELLED`; a linked motion still in `FILED` is detached and remains `FILED`, and the hearing's `version` increments.

A motion advances out of `FILED` in one of two ways: it is taken under submission — either by the cascade just described when its hearing is held, or directly by a judge — moving `FILED → UNDER_SUBMISSION` and incrementing the motion's `version`; or it is withdrawn. Withdrawal is an attorney action restricted to the moving party's counsel: the acting `attorney_user_id` must equal the moving party's `attorney_user_id`, else `ERR_NOT_MOVING_PARTY`. Withdrawal moves the motion `FILED → WITHDRAWN`, and if a `SCHEDULED` hearing is linked via `hearing_id` that hearing is cancelled as a cascade; the motion's `version` increments.

Ruling on a motion is a judge action available only from `UNDER_SUBMISSION`, and only while the case posture is not `FROZEN` (else `ERR_CASE_FROZEN`). The ruling request supplies a `ruling`, the `order_text` of the resulting order, and an optional `stays_case` flag. Each ruling creates exactly one order and sets the motion's `order_id`, but the three branches differ. A ruling of grant moves the motion `UNDER_SUBMISSION → GRANTED` and creates an order with disposition `GRANT`; if that order's `stays_case` is true, the case stay cascade is triggered. A ruling of denial moves the motion `UNDER_SUBMISSION → DENIED` and creates an order with disposition `DENY` for which `stays_case` is forced false, so denial never stays the case and never vacates deadlines. A ruling of partial grant moves the motion `UNDER_SUBMISSION → GRANTED_IN_PART` and creates an order with disposition `GRANT_IN_PART`; as with a full grant, if that order's `stays_case` is true the case stay cascade is triggered. Every ruling increments both the motion's `version` and the case's `version`. `GRANTED`, `DENIED`, `GRANTED_IN_PART`, and `WITHDRAWN` are all terminal motion states.

An order is the written disposition of a motion. It carries its `case_id`, the `motion_id` it rules on, a `disposition` mirroring the ruling (`GRANT`, `DENY`, or `GRANT_IN_PART`), the `text` of the order body, the `stays_case` flag, and an `entered_at` timestamp. An order with `stays_case` true is effective only when its disposition is `GRANT` or `GRANT_IN_PART`: in that case it stays the case. The stay cascade runs in three hops. First, the case transitions `OPEN → STAYED` (this is the system transition triggered by an order entered with `stays_case` true and a granting disposition while the case is `OPEN`). Second, every deadline under the case still in `PENDING` is moved to `VACATED`, each such vacatur decrementing the case's `open_deadline_count`. Third, posture is recomputed to `FROZEN`, which it remains while the case is `STAYED`. The case's `version` increments. A stay is lifted only by a judge: from `STAYED` the case transitions back to `OPEN`, posture is recomputed, and the case `version` increments.

### 3.6. Fee Waivers for Indigent Litigants

An attorney may request a fee waiver against a filing's fee. The request supplies the `case_id`, the target `filing_id`, the `requesting_party_id`, the declared `monthly_income_cents` (zero or greater), and the `household_size` (at least one). The waiver begins `PENDING`, and at creation — and again on every resubmission — its `eligibility_ratio` is computed. The eligibility threshold for a household is a base of 130000 cents plus 47000 cents for each additional person beyond the first; that is, the threshold equals the base plus the per-person amount multiplied by one less than the household size. The eligibility ratio is the declared monthly income in cents divided by that threshold, rounded half up to four decimal places. A ratio strictly less than 1.25 marks the request as presumptively eligible. The waiver also records a `decided_at` timestamp, set when it is finally approved or denied.

A clerk who needs more information moves the waiver `PENDING → NEEDS_INFO`. The attorney then resubmits, which moves it `NEEDS_INFO → PENDING`; resubmission is restricted to the requesting party's counsel, so the acting `attorney_user_id` must equal the requesting party's `attorney_user_id`, else `ERR_NOT_REQUESTING_PARTY`. On resubmission the attorney may optionally update `monthly_income_cents` or `household_size`, after which the `eligibility_ratio` is recomputed. This revision loop may cycle between `PENDING` and `NEEDS_INFO` any number of times.

A clerk decides the waiver from either `PENDING` or `NEEDS_INFO`. Approval requires that the target filing's `fee_status` is `ASSESSED`; if it is anything else, approval is rejected with `ERR_FEE_NOT_ASSESSED`. Approval is a depth-two cascade: it moves the waiver to `APPROVED`, sets `decided_at`, then sets the target filing's `fee_status` to `WAIVED` (hop one) and recomputes the case's `total_fees_paid_cents` (hop two); the waiver's, the filing's, and the case's `version` each increment. Denial — also available from either `PENDING` or `NEEDS_INFO` — moves the waiver to `DENIED`, leaves the target filing's `fee_status` as it stands (an assessed fee remains `ASSESSED`), sets `decided_at`, and increments the waiver's `version`. `APPROVED` and `DENIED` are terminal.

### 3.7. Judgments and Post-Judgment Interest

Entering a judgment is a judge action and the pivot from active litigation to disposition. It requires that the case be `OPEN`, that no motion under the case remains in status `FILED` or `UNDER_SUBMISSION` (else `ERR_PENDING_MOTIONS`), and that the request carry an `expected_case_version` matching the case's current `version` as described in Section 2.9. The request supplies the `case_id`, the `judgment_type` (one of `DEFAULT`, `SUMMARY`, `TRIAL`, or `DISMISSAL`), an optional `prevailing_party_id` (null for a dismissal), an optional `principal_cents` award (zero or greater, defaulting to zero), and an optional `interest_rate_bps` annual post-judgment rate in basis points (zero or greater, defaulting to zero). The judgment is created in status `ENTERED` with its `entered_at` set; the case transitions `OPEN → JUDGMENT_ENTERED`; an appeal-window deadline is created (an `APPEAL` deadline anchored on the judgment-entered event, with `interval_days` equal to the court's `appeal_window_days` and a calendar counting mode); posture is recomputed; and the case's `version` increments.

A judgment exposes a computed `total_with_interest_cents` recalculated on every read and on payoff. Post-judgment interest is simple — accrued on principal only, never compounded — and is computed over the whole elapsed span in a single multiplication. The number of elapsed days is the larger of zero and the whole number of days from the date of `entered_at` through the current clock date. The daily rate is the `interest_rate_bps` divided by 10000 (to convert basis points to a fraction) and then divided by 365. The accrued interest in cents is the `principal_cents` multiplied by that daily rate multiplied by the elapsed days, rounded half up to whole cents. The `total_with_interest_cents` is the `principal_cents` plus that accrued interest.

A judgment leaves `ENTERED` by one of three routes. A clerk may mark it satisfied, moving `ENTERED → SATISFIED` and incrementing the judgment's `version`. A judge may vacate it, but only while the case is still `JUDGMENT_ENTERED` and not yet on appeal; vacating an already-appealed judgment is rejected with `ERR_INVALID_STATE`. Vacatur moves the judgment `ENTERED → VACATED`, reverses the case `JUDGMENT_ENTERED → OPEN`, vacates every `APPEAL` deadline still in `PENDING`, and increments both the judgment's and the case's `version`. The third route — to `APPEALED` — is driven by the filing of an appeal, covered next. `SATISFIED` and `VACATED` are terminal judgment states.

### 3.8. Appeals and Record Transmittal

Filing a notice of appeal is an attorney action. It requires the case to be in `JUDGMENT_ENTERED`, requires the `filed_on` date to fall within the court's `appeal_window_days` after the judgment's `entered_at` inclusive — an appeal filed past that window is rejected with `ERR_APPEAL_WINDOW_CLOSED` — and is OCC-guarded on the case as described in Section 2.9. The request supplies the `case_id`, the `judgment_id` being appealed, the `appellant_party_id`, the `filed_on` date, an optional `record_page_count` (zero or greater, defaulting to zero), and the `expected_case_version`. The appeal is created in status `NOTICE_FILED`; the appealed judgment cascades `ENTERED → APPEALED`, which in turn drives the case `JUDGMENT_ENTERED → ON_APPEAL`; and the case's `version` increments.

The clerk then prepares the record on appeal. Preparation requires a positive `record_page_count`; an attempt with a page count of zero or less is rejected with `ERR_EMPTY_RECORD`. Preparation moves the appeal `NOTICE_FILED → RECORD_PREPARED` and computes the `transmittal_fee_cents` from the prepared page count, incrementing the appeal's `version`. The transmittal fee is a flat base of 5000 cents plus a marginal per-page charge across three tiers, where the boundaries are on cumulative page count: the first 100 pages are charged 50 cents each, pages 101 through 500 are charged 30 cents each, and every page beyond 500 is charged 15 cents each. Each page is billed at its own tier's marginal rate, so a 600-page record pays 50 cents on its first 100 pages, 30 cents on the next 400, and 15 cents on the final 100 — never a single flat rate across the whole record. Transmitting the prepared record moves the appeal `RECORD_PREPARED → TRANSMITTED`, sets `transmitted_at` to the current clock, and increments the appeal's `version`.

A judge may dismiss an appeal from either `NOTICE_FILED` or `RECORD_PREPARED`, in both cases moving it to `DISMISSED` with the same cascade: if no other non-terminal appeal remains on the case, the appealed judgment is restored `APPEALED → ENTERED` and the case is restored `ON_APPEAL → JUDGMENT_ENTERED`; the appeal's `version` increments. `TRANSMITTED` and `DISMISSED` are terminal appeal states. Once every appeal on the case is `TRANSMITTED` or `DISMISSED`, the clerk may close the case as described in Section 3.1.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. Request bodies, response payloads, and side effects for each endpoint are reconstructed from the workflow narratives in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/courts` | Create a court (configuration) | SystemAdmin |
| GET | `/courts/{id}` | Get a court | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/_clock/set_current_utc` | Set the system clock | SystemAdmin |
| POST | `/cases` | Create a case (DRAFT); mints case number | Clerk |
| GET | `/cases/{id}` | Get a case (with posture and aggregates) | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/cases` | List cases, filterable by court | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/cases/{id}/open` | Open a DRAFT case | Clerk |
| POST | `/cases/{id}/lift-stay` | Lift a stay | Judge |
| POST | `/cases/{id}/close` | Close a case | Clerk |
| POST | `/parties` | Add a party to a case | Clerk |
| GET | `/parties/{id}` | Get a party | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/parties` | List parties, filterable by case | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/filings` | e-File a document | Attorney |
| GET | `/filings/{id}` | Get a filing | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/filings` | List filings | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/filings/{id}/claim-review` | Claim a submitted filing for review | Clerk |
| POST | `/filings/{id}/accept` | Accept a filing under review | Clerk |
| POST | `/filings/{id}/reject` | Reject a filing under review | Clerk |
| POST | `/filings/{id}/pay-fee` | Record payment of an assessed filing fee | Attorney, Clerk |
| POST | `/service-of-process` | Record a service attempt | Clerk |
| GET | `/service-of-process/{id}` | Get a service-of-process record | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/service-of-process` | List service-of-process records | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/service-of-process/{id}/complete` | Mark service completed | Clerk |
| POST | `/service-of-process/{id}/fail` | Mark service failed | Clerk |
| POST | `/deadlines` | Create a deadline | Clerk |
| GET | `/deadlines/{id}` | Get a deadline | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/deadlines` | List deadlines | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/deadlines/{id}/satisfy` | Mark a deadline satisfied | Clerk |
| POST | `/deadlines/{id}/mark-missed` | Mark a past-due deadline missed | Clerk |
| POST | `/deadlines/{id}/vacate` | Vacate a pending deadline | Judge |
| POST | `/motions` | File a motion | Attorney |
| GET | `/motions/{id}` | Get a motion | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/motions` | List motions | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/motions/{id}/submit` | Take a motion under submission | Judge |
| POST | `/motions/{id}/rule` | Rule on a motion; creates an order | Judge |
| POST | `/motions/{id}/withdraw` | Withdraw a filed motion | Attorney |
| GET | `/orders/{id}` | Get an order | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/orders` | List orders | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/fee-waivers` | Request a fee waiver | Attorney |
| GET | `/fee-waivers/{id}` | Get a fee waiver | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/fee-waivers` | List fee waivers | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/fee-waivers/{id}/request-info` | Request more info | Clerk |
| POST | `/fee-waivers/{id}/resubmit` | Resubmit with updated info | Attorney |
| POST | `/fee-waivers/{id}/approve` | Approve a waiver | Clerk |
| POST | `/fee-waivers/{id}/deny` | Deny a waiver | Clerk |
| POST | `/hearings` | Schedule a hearing | Judge |
| GET | `/hearings/{id}` | Get a hearing | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/hearings` | List hearings | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/hearings/{id}/hold` | Hold a hearing | Judge |
| POST | `/hearings/{id}/continue` | Continue a hearing to a new window | Judge |
| POST | `/hearings/{id}/cancel` | Cancel a scheduled hearing | Judge |
| POST | `/judgments` | Enter a judgment (OCC-guarded) | Judge |
| GET | `/judgments/{id}` | Get a judgment (interest to current clock) | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/judgments` | List judgments | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/judgments/{id}/satisfy` | Mark a judgment satisfied | Clerk |
| POST | `/judgments/{id}/vacate` | Vacate a judgment | Judge |
| POST | `/appeals` | File a notice of appeal (OCC-guarded) | Attorney |
| GET | `/appeals/{id}` | Get an appeal | SystemAdmin, Clerk, Judge, Attorney |
| GET | `/appeals` | List appeals | SystemAdmin, Clerk, Judge, Attorney |
| POST | `/appeals/{id}/prepare-record` | Prepare the record on appeal | Clerk |
| POST | `/appeals/{id}/transmit` | Transmit the record | Clerk |
| POST | `/appeals/{id}/dismiss` | Dismiss an appeal | Judge |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_CROSS_CASE_REFERENCE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CASE_FROZEN` | 409 |
| `ERR_CASE_RESTRICTED` | 409 |
| `ERR_HEARING_CONFLICT` | 409 |
| `ERR_STATUTE_EXPIRED` | 409 |
| `ERR_FILING_FEE_UNPAID` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_WINDOW_OPEN` | 409 |
| `ERR_APPEAL_NOT_TRANSMITTED` | 409 |
| `ERR_CASE_MISSING_PARTIES` | 409 |
| `ERR_NO_ACCEPTED_COMPLAINT` | 409 |
| `ERR_PENDING_MOTIONS` | 409 |
| `ERR_CASE_NOT_OPEN` | 409 |
| `ERR_PARTY_ALREADY_SERVED` | 409 |
| `ERR_REJECTION_REASON_REQUIRED` | 422 |
| `ERR_RESUBMIT_TARGET_NOT_REJECTED` | 409 |
| `ERR_FEE_NOT_ASSESSED` | 409 |
| `ERR_DEADLINE_NOT_YET_DUE` | 409 |
| `ERR_HEARING_NOT_STARTED` | 409 |
| `ERR_EMPTY_RECORD` | 409 |
| `ERR_NOT_MOVING_PARTY` | 403 |
| `ERR_NOT_REQUESTING_PARTY` | 403 |
