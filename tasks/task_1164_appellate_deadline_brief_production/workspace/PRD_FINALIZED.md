# Appellate Practice API — Product Requirements Document

## 1. Introduction

Appellate practice is a discipline of unforgiving dates. A notice of appeal filed one day late is jurisdictional; a brief one word over the limit is stricken; a transcript order that slips silently can stall an entire briefing calendar. Small appellate practice groups currently track these obligations in spreadsheets and inbox reminders, which makes deadline computation, extension tracking, and citation compliance error-prone exactly where the cost of error is highest. This product is a practice-management API for appellate teams: it computes notice-of-appeal deadlines from the triggering judgment under each court's jurisdiction rules, walks the record on appeal from designation through transcript delivery, derives and shifts the briefing schedule as extension motions are granted, enforces page and word limits with table-of-authorities verification before anything reaches the court, and carries the case through oral argument, decision, and further-review petitions.

The API serves four kinds of users — court administrators who register courts and attorneys, admitted attorneys who draft and file, court clerks who accept filings and rule on motions, and paralegal staff who manage transcripts and citations — and it treats every deadline, version counter, and state transition as auditable data. Because appellate rules differ by jurisdiction, every court registered in the system carries its own deadline bases, brief limits, and filing mandates, and every computation described in this document is parameterized by those per-court settings. All resources are served under the `/appellate` path prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the acting role. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to invoke the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Four roles exist, spelled exactly as follows:

- **`CourtAdmin`** — a platform administrator who registers courts and attorneys and drives the test clock. When `X-User-Role` is `CourtAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`Attorney`** — an admitted lawyer who drafts briefs, designates the record, files motions and petitions, and waives argument. When `X-User-Role` is `Attorney`, `X-User-ID` is the `id` of the acting `Attorney` record; ownership checks on any resource that references an attorney — for example a case's `lead_attorney_id` or a brief's `author_attorney_id` — compare the resource's foreign-key field to `X-User-ID`. This identity binding is what makes segregation-of-duties and lead-attorney-only actions enforceable.
- **`CourtClerk`** — court staff who accept and reject filings, schedule arguments, decide motions, and enter decisions. When `X-User-Role` is `CourtClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`ParalegalStaff`** — support staff who manage transcript orders, citations, and filings but can never approve or e-file a brief. When `X-User-Role` is `ParalegalStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All four roles may read any resource through the list and fetch endpoints. Write capabilities differ per endpoint and are enumerated in §4.

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

Every list endpoint accepts two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0 and never negative. A request whose `limit` falls outside the range 1 through 100 inclusive, or whose `offset` is negative, is rejected with `ERR_PAGINATION` (HTTP 400). List responses are always sorted by `created_at` ascending, and the `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more` exactly as shown in §2.2.

### 2.4. Resource Identity and Common Fields

Every resource in the system — court, attorney, case, appeal event, deadline, record, transcript order, briefing schedule, brief, table of authorities, citation, extension motion, filing, oral argument, decision, and further-review petition — carries four system-maintained properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time, and `updated_at` records the most recent mutation; both are ISO 8601 UTC timestamps rendered with three fractional digits. The `version` is an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource, including system-driven mutations described in §3.

### 2.5. The Logical Clock

Time-sensitive rules in this document refer to "now," and "now" always means the server's logical clock rather than the host's wall clock. When the server boots, the logical clock is pinned at 2026-05-01T00:00:00Z, an instant deliberately chosen to sit at or before every ordinary fixture date so that an unset clock behaves as a fixed earliest instant instead of drifting with wall time. A `CourtAdmin` may override the logical clock through the clock-setting capability, supplying the target instant as `to_iso8601`; any role may read the current value, returned as `current_utc`. Advancing the clock mutates no entity — it changes only what "now" means for every rule evaluated afterwards. Two transitions in this document are driven purely by the passage of time — the briefing-schedule completion of §3.4 once the reply window has lapsed, and the case closure of §3.8 once the mandate has issued. The clock itself fires nothing: each time-driven rule is evaluated lazily against the current "now" — whenever the affected case or briefing schedule is fetched or listed, and before the posture and deadline gates on argument scheduling and on petition filing are evaluated — so that reading a case or its briefing schedule after a clock advance always reflects every time-driven transition the advance made due.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each takes its version field as a non-optional input. Vacating a briefing schedule requires the request to carry `expected_case_version` holding the `version` of the parent case as the caller last observed it; if the case's current `version` has advanced beyond that observed value — for example because another writer filed a brief or a petition ruling reopened the case since the clerk's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because vacating would silently undo work the caller never saw. Granting an extension motion requires the request to carry `expected_schedule_version` holding the `version` of the governing briefing schedule as the caller last observed it; a mismatch with the schedule's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because a previously granted motion may already have shifted the same target deadline and a second grant computed from a stale view would double-apply deltas. No endpoint other than these two accepts a version field.

### 2.7. Calendar Arithmetic, Precision, and Comparison Rules

Deadline arithmetic throughout the system adds whole calendar days to timestamps and preserves the time-of-day of the anchor instant; all timestamps are compared and stored at one-second precision with no rounding. Where a court's `weekend_holiday_rollforward` flag is set, any computed deadline landing on a weekend or a court holiday moves forward one calendar day at a time until it lands on a business day. Percentages are computed with integer arithmetic: fractional results are truncated downward to the nearest whole percent (floor division), never rounded. Brief-length compliance uses strict integer comparison: a brief is over its limit only when its measured length strictly exceeds the limit, so a brief sitting exactly at the limit is compliant. Scheduling conflicts use half-open interval arithmetic with strictly-less-than comparisons, so an argument that ends exactly when another begins does not overlap it.

### 2.8. Nested Resources, References, and Cascading Mutation

Many resources live beneath others — events, deadlines, records, schedules, briefs, motions, filings, arguments, decisions, and petitions all belong to a case and carry the parent's identifier as `case_id`; transcript orders belong to a record through `record_id`; a table of authorities belongs to a brief through `brief_id`; citations belong to a table through `toa_id`. When a request URL contains several resource identifiers, the server resolves them left to right — court, then case, then the nested resource — and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). Identifiers supplied in a request body rather than the URL — `court_id`, `schedule_id`, `author_attorney_id`, `brief_id`, `basis_decision_id`, and the like — are validated the same way, and a body-supplied reference that does not exist yields `ERR_FK_NOT_FOUND` (HTTP 404).

Mutations rarely stay local. Delivering a transcript can complete a record; completing a record can activate a briefing schedule; granting a motion shifts three dates and every brief that inherits them. Each subsection of §3 states exactly which cascades a workflow triggers, and every resource touched by a cascade — the primary target and each affected parent or child — has its `version` incremented and its `updated_at` refreshed.

### 2.9. Validation Pipeline and Priority Order

Requests are validated in a fixed priority order, and when several rules could fail on the same request the earliest rule's error is the one returned. The order is:

1. **Authentication** — `X-User-Role` and `X-User-ID` are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint.
2. **Authorization** — the role is permitted to invoke this endpoint per the access matrix in §4; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). Applies to every endpoint.
3. **Path existence** — every identifier in the URL resolves, left to right; otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to every resource endpoint.
4. **Body reference existence** — every foreign-key identifier supplied in the body resolves; otherwise `ERR_FK_NOT_FOUND` (HTTP 404). Applies to creation and update endpoints that take such references.
5. **State validity** — the target resource is in a state from which the requested transition exists (for example, a brief may be submitted for review only while `DRAFT`); otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to every state-transition endpoint.
6. **Segregation of duties** — on brief approval and on return-to-draft, the reviewing attorney must differ from the drafting attorney; otherwise `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403).
7. **Bar admission** — on brief creation, brief approval, brief e-filing, and petition creation, the acting attorney's `admitted_court_ids` must contain the case's court; otherwise `ERR_NOT_ADMITTED` (HTTP 403).
8. **Deadline currency** — on brief e-filing and petition filing, the act must occur at or before the governing due date; otherwise `ERR_DEADLINE_PASSED` (HTTP 409).
9. **Brief length compliance** — on brief approval, brief e-filing, and filing acceptance of a brief, the brief must not be over its court limit; otherwise `ERR_BRIEF_OVER_LIMIT` (HTTP 422).
10. **Citation verification** — on brief approval, when the court mandates electronic filing, the brief's table of authorities must exist with no unverified citations; otherwise `ERR_TOA_UNVERIFIED` (HTTP 422).
11. **Record and schedule readiness** — on brief e-filing, the record must be `COMPLETE` or `FILED` and the briefing schedule must be `ACTIVE`; otherwise `ERR_RECORD_NOT_COMPLETE` (HTTP 409).
12. **Argument overlap** — on argument scheduling, the proposed interval must not overlap another non-terminal argument on the same court; otherwise `ERR_ARGUMENT_OVERLAP` (HTTP 409).
13. **Argument notice** — on argument scheduling, the proposed start must respect the court's minimum notice window; otherwise `ERR_ARGUMENT_NOTICE_TOO_SHORT` (HTTP 422). The overlap check runs before the notice check, so a conflicting slot surfaces `ERR_ARGUMENT_OVERLAP` even when the slot is also too soon.
14. **Grant-days validity** — on motion grant, the granted days must be at least one and no more than the requested days; otherwise `ERR_GRANT_DAYS_INVALID` (HTTP 422).
15. **Stale-version rejection** — on motion grant and schedule vacate, the expected-version field must match the parent's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
16. **Service completeness** — on filing creation and on brief e-filing, the served-party list must satisfy the filing's service requirement; otherwise `ERR_SERVICE_INCOMPLETE` (HTTP 422).
17. **Decision issued** — on petition filing, the case must have reached `DECIDED`; otherwise `ERR_DECISION_NOT_ISSUED` (HTTP 409). Because deadline currency ranks higher, a petition filed both late and before decision surfaces `ERR_DEADLINE_PASSED` first.
18. **Uniqueness** — court `code` and attorney `bar_number` must be unique, and a case may have only one record and one briefing schedule while a brief may have only one table of authorities; a violation yields `ERR_DUPLICATE` (HTTP 409).

Independent of this pipeline, a request whose body is malformed, carries an unrecognized enum value, or fails a field type check is rejected with `ERR_INVALID_REQUEST` (HTTP 400). And a transition attempted against a resource already resting in a terminal state — `FILED` or `CANCELLED` for a transcript order, `ACCEPTED` or `STRICKEN` for a brief, `GRANTED`, `DENIED`, or `WITHDRAWN` for a motion or petition, `ACCEPTED` or `REJECTED` for a filing, `HELD` or `WAIVED` for an argument, `COMPLETE` or `VACATED` for a schedule, `FILED` for a record, `CLOSED` for a case — is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) rather than `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Registering Courts and Admitting Attorneys

Before any case can be opened, a `CourtAdmin` registers the courts the firm practices before. Each court is registered with a unique `code` (short identifiers such as CA9, SCOTUS, or NY-AD1), a display `name`, and a `jurisdiction_type` of `FEDERAL`, `STATE`, or `TRIBAL` — the jurisdiction type controls which deadline basis applies to rehearing computations later. The court's rule set is captured at registration: `appeal_deadline_days` is the number of days from the triggering judgment to the notice-of-appeal deadline (thirty days is the customary federal window and sixty the customary state window, and each court records its own figure), and `reply_brief_window_days` is the number of days between the appellee's brief and the reply brief. Whether the court measures briefs by words or by pages is governed by the `uses_word_count` flag: when set, briefs are limited by `max_words_opening` and `max_words_reply`; when unset, by `max_pages_opening` and `max_pages_reply`. Courts that mandate electronic filing register with `efiling_required` set, and courts whose deadlines roll off weekends and holidays register with `weekend_holiday_rollforward` set. A newly registered court starts at `version` 1. Registering a court whose `code` is already taken fails with `ERR_DUPLICATE`. The court list can be paged through and filtered by `jurisdiction_type`.

Attorneys are registered the same way, by a `CourtAdmin`, with a `bar_number` that must be unique across the platform, a `full_name`, a service `email`, and `admitted_court_ids`, the array of court identifiers before which the attorney is admitted. A duplicate `bar_number` fails with `ERR_DUPLICATE`. The attorney directory supports paging and filtering by `bar_number`. Admission matters downstream: drafting, approving, and e-filing briefs, and creating further-review petitions, are all restricted to attorneys admitted to the case's court, and an attorney who is not admitted is turned away with `ERR_NOT_ADMITTED`.

### 3.2. Opening the Appeal: Judgment, Notice, and Tolling

An appeal begins when an `Attorney` or `CourtAdmin` opens a case. The intake payload carries the `court_id` of the appellate court, the `docket_number` (unique within that court), the `caption`, the `lead_attorney_id` of the attorney of record responsible for the appeal, the side the firm represents as `appellant_side` — one of `APPELLANT`, `APPELLEE`, or `CROSS_APPELLANT` — and `judgment_entered_at`, the date the lower court entered judgment, which is the canonical trigger for all deadline computation. A `court_id` or `lead_attorney_id` that does not resolve fails with `ERR_FK_NOT_FOUND`. The new case opens with `posture` set to `OPEN`, and two things happen automatically: an appeal event of `event_type` `JUDGMENT_ENTERED` is recorded with its `occurred_at` taken from `judgment_entered_at`, and a deadline of `kind` `NOTICE_OF_APPEAL` is created with its `basis_event_id` pointing back at that judgment event.

The notice-of-appeal deadline is computed in two variants. The provisional figure, `provisional_due_at`, is computed immediately from the judgment event: take the judgment event's `occurred_at`, add the court's `appeal_deadline_days` calendar days preserving the time-of-day, and — when the court's `weekend_holiday_rollforward` flag is set — keep advancing one calendar day at a time while the result lands on a weekend or a court holiday. The provisional computation deliberately ignores any pending post-judgment motions. The operative figure, `final_due_at`, simply equals the provisional figure until something adjusts it; a deadline row also tracks `tolled` (whether a tolling event currently suspends it), `met` (whether the corresponding act has been performed), and `met_at` (when it was satisfied, null while unmet).

Post-judgment motions toll the notice deadline, and the event log is where that tolling enters the system. Attorneys, clerks, and court administrators can log an appeal event on a case, supplying an `event_type`, the `occurred_at` timestamp from the court of record, and an optional free-text `notes` annotation that defaults to an empty string. The recognized event types are `JUDGMENT_ENTERED`, `NOTICE_FILED`, `POST_JUDGMENT_MOTION_FILED`, `POST_JUDGMENT_MOTION_DECIDED`, `RECORD_COMPLETE`, `BRIEF_FILED`, and `DECISION_ISSUED`. When a `POST_JUDGMENT_MOTION_FILED` event lands, the case's unmet `NOTICE_OF_APPEAL` deadline is marked `tolled` — the clock is suspended. When the matching `POST_JUDGMENT_MOTION_DECIDED` event lands, tolling resolves: the system finds the most recent `POST_JUDGMENT_MOTION_FILED` event occurring before the decision event, measures the elapsed time from that filing to the decision, and sets `final_due_at` on each unmet `NOTICE_OF_APPEAL` deadline to `provisional_due_at` plus that tolling delta, clearing `tolled` back to false. Because the tolling delta can push the deadline substantially later, the provisional and final figures genuinely diverge on a tolled case. The event log can be paged and filtered by `event_type`, and the deadline list for a case — or across all cases — can be filtered by `kind`, by `met`, and by `basis_event_id`; deadlines computed from a particular event are also reachable as a sub-resource of that event. Across the full lifecycle the system maintains eight deadline kinds: `NOTICE_OF_APPEAL`, `RECORD_DESIGNATION`, `TRANSCRIPT_ORDER`, `OPENING_BRIEF`, `RESPONSE_BRIEF`, `REPLY_BRIEF`, `REHEARING_PETITION`, and `CERT_PETITION`.

Filing the notice itself goes through the filings workflow described in §3.6: the notice is submitted as a filing of `filing_type` `NOTICE_OF_APPEAL`, and it must serve every adverse party — a notice whose `served_party_emails` omits adverse parties is rejected with `ERR_SERVICE_INCOMPLETE`. When the clerk accepts that filing, the case's `notice_filed_at` is set to the filing's `filed_at`, the case's posture moves from `OPEN` to `RECORD_PENDING`, and three auto-creations fire: a record row in `PENDING_DESIGNATION`, a briefing schedule row in `PENDING`, and deadline rows of kinds `RECORD_DESIGNATION` and `TRANSCRIPT_ORDER`. Because a case may have only one record and one briefing schedule, an acceptance that would create a second of either violates uniqueness and fails with `ERR_DUPLICATE`. The case docket can be paged and filtered by `court_id`, `lead_attorney_id`, or `posture`.

### 3.3. Perfecting the Record: Designation and Transcripts

While the case sits in `RECORD_PENDING`, the record on appeal is assembled. The record row carries a computed `designation_due_at` — the date by which the appellant must designate the record's contents — a `designated_at` timestamp that stays null until designation occurs, and a `completeness_pct` tracking how much of the designated record has actually arrived.

Designation is performed by an `Attorney` and moves the record from `PENDING_DESIGNATION` to `DESIGNATED`. It is permitted only while the case's posture is `RECORD_PENDING` and only while no transcript orders yet exist under the record — that is, while completeness is zero or not yet computed. Designation stamps `designated_at` with the current time, increments the record's `version`, and recomputes the case posture, which may remain `RECORD_PENDING` until transcripts arrive. Designation can also be walked back: revoking a designation moves the record from `DESIGNATED` back to `PENDING_DESIGNATION`, and the transition exists only while the record stands `DESIGNATED` — once the record has advanced to `ASSEMBLING` or `COMPLETE`, revocation is rejected with `ERR_INVALID_STATE` (and from the terminal `FILED` state with `ERR_ALREADY_TERMINAL`, per §2.9). Revocation is permitted only while no transcript order under the record has reached `DELIVERED` or `FILED`. Revocation clears `designated_at` to null and cancels every transcript order still sitting in `ORDERED` or `IN_PREPARATION`.

Transcript orders are placed under a designated record by an `Attorney` or `ParalegalStaff`, specifying the `hearing_date` to be transcribed, the `court_reporter` (a reporter name or firm), and an `estimated_pages` length. A new order starts in `ORDERED` with `ordered_at` stamped at creation, `actual_pages` at 0, `delivered_at` null, and a `due_at` computed as `ordered_at` plus the court's transcript delivery window — thirty days unless the court configures otherwise. Every change to any transcript order under a record recomputes the record's `completeness_pct`: counting only orders that are not `CANCELLED` as the designated set, and counting orders that are `DELIVERED` or `FILED` as delivered, the percentage is one hundred times the delivered count divided by the designated count, truncated down to a whole percent; when no non-cancelled orders exist at all, completeness is 0.

The court reporter's workflow is driven by the clerk. Marking an order as begun moves it from `ORDERED` to `IN_PREPARATION` and is allowed only while the record is `DESIGNATED` or `ASSEMBLING`; the first order to enter preparation bubbles the record up from `DESIGNATED` to `ASSEMBLING`. Delivering a transcript moves the order from `IN_PREPARATION` to `DELIVERED`, and the delivery payload must carry an `actual_pages` count greater than zero; delivery stamps `delivered_at`, recomputes completeness, and — when no order under the record remains in `ORDERED` or `IN_PREPARATION` and at least one order stands at `DELIVERED` or `FILED` — completes the record: the record moves from `ASSEMBLING` to `COMPLETE`, its `completeness_pct` is set to a full 100, the case posture recomputes from `RECORD_PENDING` to `BRIEFING` when a briefing schedule exists, the schedule itself activates as described in §3.4, and deadline rows for `OPENING_BRIEF`, `RESPONSE_BRIEF`, and `REPLY_BRIEF` are auto-created. Once delivered, a transcript can be filed with the court by an `Attorney`, moving from `DELIVERED` to `FILED`, provided the record is `ASSEMBLING` or `COMPLETE`. Cancellation runs the other way: an `Attorney` or `ParalegalStaff` may cancel an order while it is `ORDERED`, or while it is `IN_PREPARATION` provided no delivery has been recorded, moving it to `CANCELLED` and recomputing completeness. `CANCELLED` and `FILED` are the terminal states of a transcript order. The transcript list for a record pages and filters by `status`.

When assembly is done, an `Attorney` files the assembled record with the court. Filing requires the record to be `COMPLETE`; it moves the record to `FILED` — the record's terminal state — and creates a filing row of `filing_type` `RECORD` in `SUBMITTED` status. Separately, when the clerk accepts a filing of type `RECORD`, that acceptance also drives the record to `FILED` (see §3.6).

### 3.4. The Briefing Schedule and Extensions of Time

The briefing schedule created alongside the record sits in `PENDING` until the record completes. The moment the record reaches `COMPLETE`, the schedule moves from `PENDING` to `ACTIVE` and its three dates are computed by forward anchoring on the record's completion instant: `opening_due_at` is the anchor plus the court's opening-brief window (forty days by default), `response_due_at` is the opening date plus the court's response window (thirty days by default), and `reply_due_at` is the response date plus the court's `reply_brief_window_days`. Time-of-day is preserved from the anchor throughout.

When a deadline proves too tight, an `Attorney` files a motion for extension of time, naming the governing schedule as `schedule_id`, the `target` deadline the motion seeks to move — `OPENING`, `RESPONSE`, or `REPLY` — a `requested_days` count that must be greater than zero, and a good-cause `reason`. The motion is born `PENDING` with `granted_days` at 0 and `decided_at` null.

Ruling belongs to the clerk, and granting is the most consequential write in the system, so it is guarded twice. The grant payload must carry a `granted_days` that is at least one and no more than the motion's `requested_days` — anything outside that band is rejected with `ERR_GRANT_DAYS_INVALID` — and the schedule must still be `ACTIVE`. The payload must also carry `expected_schedule_version` equal to the schedule's current `version`; if the schedule has advanced since the clerk last read it, the grant is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than risk double-applying a delta that a previously granted motion already shifted. Checks run in priority order — motion state first, then grant-days validity, then schedule freshness.

A granted motion cascades. The motion's `granted_days` is recorded and `decided_at` stamped; then the schedule dates shift forward by the granted delta, in a depth-limited cascade: targeting `OPENING` shifts `opening_due_at`, `response_due_at`, and `reply_due_at` all forward by the same delta, because the response is anchored to the opening and the reply to the response; targeting `RESPONSE` shifts `response_due_at` and `reply_due_at`; targeting `REPLY` shifts `reply_due_at` alone. After any shift the invariant holds that the opening date never falls after the response date nor the response after the reply. When several motions have been granted on the same schedule, their shifts apply in chronological order of `decided_at`, ties broken by creation order — the final dates are order-sensitive across motions. Every brief whose `brief_type` matches the target or any cascaded target has its `due_at` re-derived from the shifted schedule, every deadline row of the matching kind has its `final_due_at` recomputed as its `provisional_due_at` plus the total granted days, and the schedule's `extensions_granted_count` increments by one. Both the schedule and the motion increment their `version`. A denied motion is simpler: `PENDING` to `DENIED`, `granted_days` stays 0, and `decided_at` is stamped. The lead attorney on the case — the one whose `id` matches the case's `lead_attorney_id` — may instead withdraw a pending motion, moving it from `PENDING` to `WITHDRAWN` with `decided_at` stamped; withdrawal by anyone else is forbidden. `GRANTED`, `DENIED`, and `WITHDRAWN` are all terminal for a motion.

The schedule itself completes when the briefing is done: from `ACTIVE` it moves to `COMPLETE` once at least one `OPENING` brief and one `RESPONSE` brief under the schedule stand `ACCEPTED` and, in addition, either a `REPLY` brief is `ACCEPTED` or the current time has passed `reply_due_at`. Completion moves the case posture from `BRIEFING` to `ARGUMENT_PENDING` and auto-creates an oral argument in `REQUESTED` (§3.7). The completion rule is evaluated whenever a brief filing under the schedule is accepted and — because the reply-window branch depends only on the clock — lazily on the next evaluation described in §2.5 once the window has lapsed; the schedule does not leave `ACTIVE` at the instant the window closes on its own. A schedule can also be vacated by a `CourtClerk` or `CourtAdmin`. Vacating from `ACTIVE` is allowed only while no brief under the schedule has reached `EFILED` or `ACCEPTED`; it returns every brief under the schedule to `DRAFT`, marks every brief-type deadline row unmet, and moves the schedule to `VACATED`. Vacating from `PENDING` carries no preconditions. Either way the request must carry `expected_case_version` matching the case's current `version` — a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412) — and a successful vacate increments both the schedule's and the case's `version`. `COMPLETE` and `VACATED` are the schedule's terminal states. Motions can be listed per case or across cases, filtered by `schedule_id`, `status`, or `target`, and the motions targeting a particular schedule are reachable as a sub-resource of that schedule.

### 3.5. Drafting, Reviewing, and Filing Briefs

Briefs are created in `DRAFT` by an `Attorney` against a case, with a payload naming the governing `schedule_id`, the `brief_type` — `OPENING`, `RESPONSE`, `REPLY`, or `AMICUS` — the drafting attorney as `author_attorney_id`, and the current `page_count` and `word_count`. An author not admitted to the case's court is rejected with `ERR_NOT_ADMITTED`. The new brief inherits its `due_at` from the schedule according to its type, and that date is re-derived whenever the schedule shifts. Creation also auto-creates the brief's table of authorities — one per brief, enforced by uniqueness — with `citation_count`, `verified_count`, and `unverified_count` all at 0 and `generated_at` null until the table's first generation pass.

Length compliance is recomputed on every edit and is deliberately dual-variant. When the court's `uses_word_count` flag is set, the applicable limit is `max_words_reply` for a `REPLY` brief and `max_words_opening` for every other type, and the measured length is the brief's `word_count`; when the flag is unset, the limit is `max_pages_reply` for a `REPLY` and `max_pages_opening` otherwise, measured against `page_count`. The brief's `over_limit` flag is set only when the measured length strictly exceeds the applicable limit — a brief sitting exactly at the limit is compliant. Because the two variants measure different quantities against different limits, the same draft can be over-limit under one variant and compliant under the other; the court's flag decides which reading governs. While a brief is in `DRAFT` or `IN_REVIEW`, its author may update `page_count` and `word_count`, which recomputes `over_limit` and increments the brief's `version`; edits in any other state are rejected with `ERR_INVALID_STATE`.

Review follows a strict segregation of duties. The drafting attorney — and only the drafter, meaning the request's `X-User-ID` must equal the brief's `author_attorney_id` — submits the draft for review, moving it from `DRAFT` to `IN_REVIEW`, and only while the case posture is `BRIEFING` or `RECORD_PENDING`. Approval must come from a different attorney: if the approving request's `X-User-ID` equals `author_attorney_id`, the attempt fails with `ERR_SELF_APPROVAL_FORBIDDEN`. Approval is the most heavily guarded transition on a brief and its checks run in priority order — the brief must be `IN_REVIEW` (state), the approver must differ from the author (segregation), the approver must be admitted to the case's court (admission), the brief must not be `over_limit` (length), and finally, when the court mandates electronic filing, the table of authorities must exist with `unverified_count` equal to zero, else `ERR_TOA_UNVERIFIED`. A self-approval attempt on an over-length brief therefore surfaces `ERR_SELF_APPROVAL_FORBIDDEN`, not the length error. A clean approval moves the brief from `IN_REVIEW` to `READY`. Alternatively the reviewer — again, someone other than the author — may return the brief for revision, moving it from `IN_REVIEW` back to `DRAFT`; this cycle between `DRAFT` and `IN_REVIEW` may repeat as many times as needed.

Citation work happens on the table of authorities while the brief is drafted. An `Attorney` or `ParalegalStaff` adds citations to the table by supplying the `raw_text` exactly as it appears in the brief and an `authority_type` of `CASE`, `STATUTE`, `RULE`, or `SECONDARY`; the system derives the `normalized` citation form, starts each citation with `verified` false and `verified_at` null, and recomputes the table's counts. Verification — available to `ParalegalStaff` and `Attorney` — marks a citation `verified`, stamps `verified_at`, and again recomputes counts. The table's arithmetic is simple aggregation: `citation_count` is the number of citations under the table, `verified_count` is the number of those verified, and `unverified_count` is the difference between the two. During drafting the provisional reading matters most — any positive `unverified_count` blocks approval when the court requires e-filing — while after a verification pass the `verified_count` is authoritative for the compliance check. Adding a citation increments the table's `version`; verifying one increments both the citation's and the table's. The citation list pages and filters by `verified` and `authority_type`.

E-filing is the brief's point of no return, performed by an `Attorney` whose admission is checked again at this gate. The checks run in priority order: the brief must be `READY` (state); the attorney must be admitted (`ERR_NOT_ADMITTED`); the filing must occur at or before the brief's `due_at` — a late filing is rejected with `ERR_DEADLINE_PASSED`; the brief must not be `over_limit`; the record must be `COMPLETE` or `FILED` and the schedule must be `ACTIVE`, else `ERR_RECORD_NOT_COMPLETE`; and the `served_party_emails` list must name at least one served party, else `ERR_SERVICE_INCOMPLETE`. The method requirement — that the court mandate electronic filing or that the filing be explicitly electronic — is satisfied by construction, since this operation always produces an `EFILE` filing. A successful e-filing moves the brief from `READY` to `EFILED`, creates a filing row of `filing_type` `BRIEF`, `method` `EFILE`, status `SUBMITTED`, and increments both the brief's and the case's `version`. The corresponding brief deadline is marked met when the filing is accepted (§3.6).

Even after acceptance, a brief can be struck. A `CourtClerk` strikes an `ACCEPTED` brief, supplying a `reason` that cites the court's order; the brief moves to `STRICKEN`, the deadline's `met` flag is reset to false as a compensating reversal, the case posture is recomputed, and the brief's `version` increments. The brief lifecycle's terminal states are `ACCEPTED`, `REJECTED`, and `STRICKEN` — though as §3.6 describes, a rejected brief filing immediately compensates by returning the brief to `DRAFT`, so `REJECTED` is never a resting place in practice. Briefs are listed per case (filterable by `brief_type` and `status`), per schedule, per authoring attorney, or across the platform with filters on `schedule_id`, `author_attorney_id`, `brief_type`, and `status`.

### 3.6. Clerk Review of Filings

Every act that reaches the court is represented as a filing: the notice of appeal, the record, briefs, extension motions, and further-review petitions. A filing row records its `filing_type` — one of `NOTICE_OF_APPEAL`, `RECORD`, `BRIEF`, `EXTENSION_MOTION`, `REHEARING_PETITION`, or `CERT_PETITION` — the `method` (`EFILE`, `PAPER`, or `HAND`), the `served_party_emails` array, and a `brief_id` that is set only when the filing is a brief and null otherwise. Filing creation is available to `Attorney` and `ParalegalStaff`; the row is born `SUBMITTED` with `filed_at` stamped at creation, and when the method is `EFILE` a `confirmation_number` is generated immediately, while `PAPER` and `HAND` filings carry a null `confirmation_number` until the clerk stamps one. Service is enforced at creation: an electronically filed brief must serve at least one party email, and a notice of appeal must serve all adverse parties, with violations rejected as `ERR_SERVICE_INCOMPLETE`.

Acceptance and rejection belong to the `CourtClerk` alone. A filing can be decided only while `SUBMITTED` — anything else is `ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` once decided. Acceptance runs its checks in priority order: state first, then, for brief filings, the brief must not be `over_limit` (`ERR_BRIEF_OVER_LIMIT`), and an electronic filing cannot be accepted with an empty `served_party_emails` list. What acceptance triggers depends on the filing type. Accepting a `BRIEF` filing moves the brief from `EFILED` to `ACCEPTED`, sets the corresponding deadline's `met` to true with `met_at` stamped, and — when the accepted brief was the response brief — opens the reply window on the schedule. Accepting a `NOTICE_OF_APPEAL` filing stamps the case's `notice_filed_at` from the filing's `filed_at` and moves the case posture from `OPEN` to `RECORD_PENDING`, auto-creating the record, the briefing schedule, and the record-phase deadlines as described in §3.2. Accepting a `RECORD` filing moves the record to `FILED`. Accepting a `REHEARING_PETITION` or `CERT_PETITION` filing moves the petition to `FILED`. Every acceptance increments the filing's `version`, and when the acceptance changes the case's posture the case's `version` increments as well.

Rejection takes a `reason` and moves the filing from `SUBMITTED` to `REJECTED`. Rejection of a brief filing compensates: the brief returns from `EFILED` to `DRAFT` so it can be redrafted. The filing's `version` increments. Filings are listed per case, per brief, or across the platform with filters on `brief_id`, `filing_type`, and `status`.

### 3.7. Oral Argument and Moot Preparation

When the briefing schedule completes and the case posture reaches `ARGUMENT_PENDING`, an oral argument row is auto-created in `REQUESTED`. After a continuance, an `Attorney` or `CourtClerk` may also re-request argument manually, supplying the desired `scheduled_start` (in UTC), a positive `duration_minutes`, and the `panel_judges` array.

Scheduling is the clerk's job and is guarded by two temporal rules, evaluated with the overlap check first. The proposed interval — from `scheduled_start` to `scheduled_start` plus `duration_minutes`, treated as half-open — is compared against every other argument on the same court that stands `SCHEDULED` or `HELD`: the proposed and existing intervals conflict only when the proposed start falls strictly before the existing interval's end and the existing start falls strictly before the proposed interval's end. Back-to-back arguments, where one's end coincides exactly with the other's start, are adjacent rather than overlapping and are permitted; a genuine conflict is rejected with `ERR_ARGUMENT_OVERLAP`. The proposed start must also respect the court's minimum notice window — at least the court's argument-notice setting, fourteen days by default, beyond the current time — and a slot inside that window is rejected with `ERR_ARGUMENT_NOTICE_TOO_SHORT`. The case must still be in `ARGUMENT_PENDING`. A clean scheduling moves the argument from `REQUESTED` to `SCHEDULED`.

Three exits follow. Once the current time reaches `scheduled_start`, the clerk may mark the argument held, moving it from `SCHEDULED` to `HELD`; the case then moves from `ARGUMENT_PENDING` to `DECIDED` as soon as a decision row is entered (§3.8). Before the start time, the clerk may instead continue the argument: it passes through `CONTINUED` and cycles back to `REQUESTED`, with `scheduled_start` cleared for rescheduling. And the lead attorney — identified by matching `X-User-ID` to the case's `lead_attorney_id` — may waive argument outright, moving it from `REQUESTED` to `WAIVED` and letting the case proceed to decision on the briefs. `HELD` and `WAIVED` are terminal. Separately from the calendar, anyone on the team — `Attorney` or `ParalegalStaff` — may log a moot practice session, which sets `moot_completed` to true and increments the argument's `version` without touching its scheduling state. The argument list for a case filters by `status`.

### 3.8. Decisions, Mandates, and Further Review

A decision is entered by a `CourtClerk` or `CourtAdmin` with an `outcome` of `AFFIRMED`, `REVERSED`, `REMANDED`, `DISMISSED`, or `MIXED` and an `issued_at` date; entry requires the case's argument to stand `HELD` or `WAIVED`. Two downstream dates are computed at entry. The `rehearing_deadline_at` is `issued_at` plus a jurisdiction-dependent window — fourteen calendar days for a `FEDERAL` court, thirty for any other jurisdiction — and the same ninety-day window that governs certiorari petitions is anchored at `issued_at` as well. The `mandate_at`, the date the mandate issues, is computed from the court's rules once the rehearing window has closed. Entering the decision moves the case posture from `ARGUMENT_PENDING` to `DECIDED` and auto-creates two deadline rows, of kinds `REHEARING_PETITION` and `CERT_PETITION`. A `DECISION_ISSUED` appeal event may be logged to keep the event trail complete.

Further review begins with a petition drafted by an `Attorney` admitted to the case's court. The petition names a `petition_type` — `REHEARING`, `REHEARING_EN_BANC`, or `CERTIORARI` — and the decision it challenges as `basis_decision_id`. The new petition sits in `DRAFT` with `filed_at` null and a `due_at` computed from the decision's `issued_at` plus the applicable court petition window: the fourteen- or thirty-day rehearing window for `REHEARING` and `REHEARING_EN_BANC`, the ninety-day window for `CERTIORARI`.

Filing the petition is deadline-checked first: the filing must occur at or before `due_at`, else `ERR_DEADLINE_PASSED`; the case must also stand `DECIDED`, else `ERR_DECISION_NOT_ISSUED`, and because deadline currency outranks the decision check, a petition that is both early-of-no-decision and late surfaces the deadline error first. A clean filing moves the petition from `DRAFT` to `FILED` and creates a filing row of the matching `filing_type`.

The clerk rules on filed petitions. Granting a `REHEARING` or `REHEARING_EN_BANC` petition reopens the case: posture moves from `DECIDED` back to `BRIEFING` and a fresh briefing schedule is created in `PENDING`, starting the briefing cycle over. Granting a `CERTIORARI` petition closes the case instead, since a granted certiorari transfers jurisdiction out of the court. Denying a petition recomputes the decision's `mandate_at` as the current time plus the court's mandate-delay setting, and when no other petition remains in `DRAFT` or `FILED` the case posture moves to `CLOSED`. The petitioner may also withdraw a petition while it is still `DRAFT`, moving it to `WITHDRAWN`. `GRANTED`, `DENIED`, and `WITHDRAWN` are terminal.

The case closes on its own once the mandate issues: when the current time reaches `mandate_at` and no petition remains in `DRAFT` or `FILED`, the case moves from `DECIDED` to `CLOSED`, its terminal posture. Like schedule completion, this closure is time-driven and is applied lazily on the next evaluation described in §2.5 rather than at the instant the mandate issues. Petitions are listed per case, per challenged decision, or across the platform with filters on `basis_decision_id`, `petition_type`, and `status`; decisions themselves are listed per case. The full posture arc — `OPEN` to `RECORD_PENDING` to `BRIEFING` to `ARGUMENT_PENDING` to `DECIDED` to `CLOSED`, with the rehearing-driven loop from `DECIDED` back to `BRIEFING` — is always readable as the case's computed `posture`.

## 4. Endpoint Definitions

All endpoints are mounted under `/appellate`. Endpoints that create a new resource return HTTP 201; endpoints that modify an existing resource, trigger a state transition, or read data return HTTP 200. The table below is a summary only — request payloads, response shapes, preconditions, and side effects are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /appellate/courts | Register a court with jurisdiction rules and brief limits | CourtAdmin |
| GET | /appellate/courts/{id} | Fetch a court | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/courts | List courts (paginated) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/attorneys | Register an attorney | CourtAdmin |
| GET | /appellate/attorneys/{id} | Fetch an attorney | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/attorneys | List attorneys (paginated) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/cases | Open a new appellate case | Attorney, CourtAdmin |
| GET | /appellate/cases/{id} | Fetch a case with computed posture | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/cases | List cases (paginated, filterable) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/cases/{id}/events | Log an appeal event (notice filed, post-judgment motion, etc.) | Attorney, CourtClerk, CourtAdmin |
| GET | /appellate/cases/{id}/events | List events for a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/events/{id} | Fetch a single event | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/cases/{id}/deadlines | List deadlines for a case (provisional + final) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/deadlines/{id} | Fetch a deadline | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/deadlines | Filtered list of deadlines across cases | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/events/{id}/deadlines | Deadlines computed from this event | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/cases/{id}/record | Fetch the case's record (1:1) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/records/{id} | Fetch record by id | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/records/{id}/designate | Designate record contents | Attorney |
| POST | /appellate/records/{id}/revoke-designation | Revoke designation (allowed only if no transcripts delivered) | Attorney |
| POST | /appellate/records/{id}/file | File the assembled record with the court | Attorney |
| POST | /appellate/records/{id}/transcript-orders | Order a transcript under a designated record | Attorney, ParalegalStaff |
| GET | /appellate/records/{id}/transcript-orders | List transcripts for a record | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/transcript-orders/{id} | Fetch a transcript order | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/transcript-orders/{id}/begin-preparation | Mark transcript in preparation (clerk) | CourtClerk |
| POST | /appellate/transcript-orders/{id}/deliver | Mark transcript delivered with actual page count | CourtClerk |
| POST | /appellate/transcript-orders/{id}/file | File transcript with court | Attorney |
| POST | /appellate/transcript-orders/{id}/cancel | Cancel a transcript order | Attorney, ParalegalStaff |
| GET | /appellate/cases/{id}/briefing-schedule | Fetch the case's briefing schedule (1:1) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/briefing-schedules/{id} | Fetch a schedule | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/briefing-schedules/{id}/vacate | Vacate the schedule (OCC-guarded) | CourtClerk, CourtAdmin |
| POST | /appellate/cases/{id}/briefs | Create a brief in DRAFT | Attorney |
| GET | /appellate/cases/{id}/briefs | List briefs on a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/briefs/{id} | Fetch a brief | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| PATCH | /appellate/briefs/{id} | Update page/word counts (DRAFT or IN_REVIEW only) | Attorney |
| POST | /appellate/briefs/{id}/submit-review | Author submits brief for review | Attorney |
| POST | /appellate/briefs/{id}/approve | Reviewer approves brief (segregation of duties enforced) | Attorney |
| POST | /appellate/briefs/{id}/return-draft | Reviewer returns brief for revision (cyclic loop) | Attorney |
| POST | /appellate/briefs/{id}/efile | E-file the brief with the court | Attorney |
| POST | /appellate/briefs/{id}/strike | Strike an accepted brief (clerk action) | CourtClerk |
| GET | /appellate/briefing-schedules/{id}/briefs | Briefs under a briefing schedule | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/briefs | Filtered list of briefs | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/attorneys/{id}/briefs | Briefs authored by an attorney | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/briefs/{id}/toa | Fetch TOA for a brief (1:1) | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/toas/{id} | Fetch a TOA | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/toas/{id}/citations | Add a citation to a TOA | Attorney, ParalegalStaff |
| GET | /appellate/toas/{id}/citations | List citations under a TOA | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/citations/{id}/verify | Verify a citation against authority source | ParalegalStaff, Attorney |
| POST | /appellate/cases/{id}/extension-motions | File a motion for extension of time | Attorney |
| GET | /appellate/cases/{id}/extension-motions | List extension motions on a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/extension-motions/{id} | Fetch a motion | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/extension-motions | Filtered list of extension motions | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/briefing-schedules/{id}/extension-motions | Extension motions targeting a schedule | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/extension-motions/{id}/grant | Grant the motion with a specific number of days (OCC-guarded) | CourtClerk |
| POST | /appellate/extension-motions/{id}/deny | Deny the motion | CourtClerk |
| POST | /appellate/extension-motions/{id}/withdraw | Withdraw the motion (lead attorney only) | Attorney |
| POST | /appellate/cases/{id}/filings | Create a filing (notice of appeal, record, motion, petition) | Attorney, ParalegalStaff |
| GET | /appellate/cases/{id}/filings | List filings on a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/filings/{id} | Fetch a filing | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/filings | Filtered list of filings | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/briefs/{id}/filings | Filings associated with a brief | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/filings/{id}/accept | Clerk accepts a filing | CourtClerk |
| POST | /appellate/filings/{id}/reject | Clerk rejects a filing | CourtClerk |
| POST | /appellate/cases/{id}/oral-arguments | Request oral argument (manual re-request after continuance) | Attorney, CourtClerk |
| GET | /appellate/cases/{id}/oral-arguments | List oral arguments for a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/oral-arguments/{id} | Fetch an oral argument | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/oral-arguments/{id}/schedule | Schedule a requested argument (overlap + notice enforced) | CourtClerk |
| POST | /appellate/oral-arguments/{id}/mark-held | Mark argument held | CourtClerk |
| POST | /appellate/oral-arguments/{id}/continue | Continue (postpone) a scheduled argument; returns to REQUESTED | CourtClerk |
| POST | /appellate/oral-arguments/{id}/waive | Lead attorney waives oral argument | Attorney |
| POST | /appellate/oral-arguments/{id}/log-moot | Log a moot (practice) session for an argument | Attorney, ParalegalStaff |
| POST | /appellate/cases/{id}/decisions | Enter a decision | CourtClerk, CourtAdmin |
| GET | /appellate/cases/{id}/decisions | List decisions on a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/decisions/{id} | Fetch a decision | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/cases/{id}/petitions | Create a further-review petition (draft) | Attorney |
| GET | /appellate/cases/{id}/petitions | List petitions on a case | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/petitions/{id} | Fetch a petition | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/petitions | Filtered list of petitions | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| GET | /appellate/decisions/{id}/petitions | Petitions challenging a decision | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |
| POST | /appellate/petitions/{id}/file | File the petition (must be within due_at) | Attorney |
| POST | /appellate/petitions/{id}/grant | Grant the petition (clerk) | CourtClerk |
| POST | /appellate/petitions/{id}/deny | Deny the petition (clerk) | CourtClerk |
| POST | /appellate/petitions/{id}/withdraw | Withdraw a draft petition | Attorney |
| POST | /appellate/_clock/set_current_utc | Set the logical clock (test-driving; boots pinned at 2026-05-01T00:00:00Z) | CourtAdmin |
| GET | /appellate/_clock/current_utc | Read the current logical clock | CourtAdmin, Attorney, CourtClerk, ParalegalStaff |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SELF_APPROVAL_FORBIDDEN | 403 |
| ERR_NOT_ADMITTED | 403 |
| ERR_DEADLINE_PASSED | 409 |
| ERR_BRIEF_OVER_LIMIT | 422 |
| ERR_TOA_UNVERIFIED | 422 |
| ERR_RECORD_NOT_COMPLETE | 409 |
| ERR_ARGUMENT_OVERLAP | 409 |
| ERR_ARGUMENT_NOTICE_TOO_SHORT | 422 |
| ERR_GRANT_DAYS_INVALID | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_SERVICE_INCOMPLETE | 422 |
| ERR_DECISION_NOT_ISSUED | 409 |
| ERR_DUPLICATE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_PAGINATION | 400 |
