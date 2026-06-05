# FOIA Information Request API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the FOIA Information Request API, a system that administers the full lifecycle of public-records requests under the Freedom of Information Act, from intake through final determination, appeal, and third-party (Reverse FOIA) negotiation. The domain is unusually procedural: a single request must be perfected, assigned, costed against one of several fee tiers, reviewed record-by-record against nine statutory exemptions, and resolved before a strict working-day deadline that can be tolled, extended, and ultimately judged met or missed. Every consequential action is logged to an append-only audit trail.

The system serves four kinds of actors with deliberately separated authority. Members of the public submit requests, pay assessed fees, and appeal outcomes; agency officers perfect, process, and determine those requests; a distinct appellate authority adjudicates appeals — and, critically, the officer who issued a determination may never sit in judgment of its appeal. Third-party businesses whose confidential records surface in a search are given a chance to object before disclosure. Layered atop this are physical logistics: reading rooms where requesters inspect released records and secure review stations where officers work, each governed by its own booking-conflict geometry.

Because deadlines, appeal windows, and reverse-notice windows are all time-sensitive, the system exposes a test-driving clock so that the passage of working days and calendar days can be simulated deterministically. Throughout, all monetary amounts are tracked in integer cents, and concurrency on the central request entity is protected by optimistic version checks so that no determination is ever issued against a stale view of the case.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `Requester`, `FoiaOfficer`, `AppealAuthority`, and `Submitter`. When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

All four roles are entity-backed; `X-User-ID` is interpreted against a persisted entity in each case. When `X-User-Role` is `Requester`, `X-User-ID` is the `id` of the acting `Requester`; ownership checks on any resource that references a `Requester` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `FoiaOfficer`, `X-User-ID` is the `id` of the acting `FoiaOfficer`; an assignment records this identifier as the request's `assigned_officer_id`, and an officer's clearance to invoke a Glomar response is read from that officer's own record. When `X-User-Role` is `AppealAuthority`, `X-User-ID` is the `id` of the acting `AppealAuthority`; taking up an appeal records this identifier as the appeal's `assigned_authority_id`. When `X-User-Role` is `Submitter`, `X-User-ID` is the `id` of the acting `Submitter`; a submitter may only act on an objection whose `submitter_id` equals `X-User-ID`.

Ownership is enforced for the ownership-scoped operations as follows: a requester may pay, withdraw, or file an appeal against a request only when the request's `requester_id` equals the acting requester's `id`; a submitter may formally object only when the objection's `submitter_id` equals the acting submitter's `id`. A violation of any of these ownership conditions is rejected with `ERR_NOT_RESOURCE_OWNER`. Segregation of duties is structural: officers and appeal authorities are disjoint roles, so the authority who adjudicates an appeal is by construction never the officer who issued the underlying determination.

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

For endpoints that return lists of resources, pagination is controlled via the `limit` and `offset` query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, with three fractional digits, indicating when the resource was last modified. It is refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that begins at its initial value and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control.

Two entities are deliberate exceptions: the `Exemption` and the `AuditEvent` are append-only, immutable records. Each carries only `id` and `created_at`; neither has an `updated_at` field nor a `version` field. The audit trail in particular is never edited after an event is appended.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource nested under a parent — for example, the records, exemptions, fee estimate, deadline, appeals, or audit events of a particular request, or the bookings of a particular reading room or review station. For any such path, the system validates the existence of each path-referenced identifier in strict left-to-right order. The first identifier that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any deeper identifier or any body content is considered. Beyond path identifiers, any foreign key supplied in a request body — such as a `requester_id`, `submitter_id`, `record_id`, `request_id`, `room_id`, or `station_id` — must reference an existing entity; a dangling body foreign key is rejected with `ERR_FK_NOT_FOUND`.

### 2.6. Validation Ordering

When several checks could apply to a single operation, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then resource-ownership for ownership-scoped operations (`ERR_NOT_RESOURCE_OWNER`), then existence of path-referenced resources (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_FK_NOT_FOUND`), then the structural validity of the request body — required fields present and well-typed, enum values within their declared sets, and numeric bounds satisfied such as a page count of at least 1 and hour figures of at least 0 (`ERR_INVALID_REQUEST`). Only after all of those pass does the system evaluate whether the target resource is in a state that permits the requested transition (`ERR_INVALID_STATE`), and then the domain-specific business rules described throughout Section 3. This ordering means, for instance, that an unauthenticated call to a non-existent resource reports the authentication failure, not the missing resource.

### 2.7. Monetary Precision and Fee Arithmetic

All money in the system is represented and stored as integer cents — there are no fractional-cent values in any stored field or response. Where a fee computation could produce a fractional cent, the value is rounded half up to the nearest whole cent. The fee calculation is composed of separately computed components (search cost, review cost, and duplication cost); each component is rounded to whole cents first, and only then are the rounded components summed. This round-per-component-then-sum ordering is mandatory and is not interchangeable with summing first and rounding once. The public-interest waiver score is likewise an integer in the range 0 through 100, obtained by rounding half up.

### 2.8. The Working-Day Deadline Clock

Each perfected request carries a single processing deadline whose arithmetic is measured in working days, where a working day is any day that is not a Saturday or a Sunday. Adding N working days to a date means advancing the calendar day by day, counting only the days that are neither Saturday nor Sunday, until N such days have been counted. The base deadline is the receipt instant advanced by 20 working days. The operative deadline is the base deadline further advanced by the working days added by any extension plus the cumulative tolled working days. Deadlines resolve at whole-day granularity, fixed to the final instant of the computed working day (23:59:59.999Z). A request additionally carries a deadline dimension, exposed as its computed `deadline_status`, that runs in parallel with its lifecycle status and may be `RUNNING`, `TOLLED`, `EXTENDED`, `MET`, or `MISSED`; how this `deadline_status` changes is described in the workflow narratives of Section 3.

### 2.9. Optimistic Concurrency Control on Determinations

The central request entity is protected against lost updates by an optimistic version check on the operations that finalize its outcome. Issuing a determination requires the client to supply `expected_request_version` carrying the version of the request the officer last observed. If that value does not match the request's current `version`, the determination is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412), because an intervening write — a fee recategorization, a granted waiver, or an applied extension, each of which advances the version and can change which determination branch is valid — means the officer would otherwise be deciding against a stale view of the case. The same `expected_request_version` field is required when invoking a Glomar response, when recording a fee estimate, and when adjudicating a fee waiver; each of those operations also advances the request's `version` by one on success. Operations that are not enumerated here do not take a version field.

### 2.10. Hierarchical Consistency and Cascades

A number of operations mutate more than one entity at once, and the secondary effects are as binding as the primary one. When a fee estimate or a payment changes a request's fee posture, the requester's `outstanding_balance_cents` is recomputed. When an appellate body remands a case, the request reopens and every one of its records is reset, while the deadline dimension returns to `RUNNING`. When an objection is sustained, the affected record is withheld and a citing exemption is created for it. Every such mutation refreshes the mutated resource's `updated_at` and, for entities that carry one, increments its `version`. Each consequential action also appends an `AuditEvent` to the request's append-only trail; each audit event records its `event_type`, a human-readable `detail`, and the `actor_role` that triggered it. The specific cascades are documented alongside the workflows that cause them in Section 3.

## 3. Business Logic & Workflows

### 3.1. Registering the Actors

Before any request can flow through the system, the participating parties are registered. A requester is registered with a `full_name`, an `email` that must be non-empty and unique across all requesters, a self-declared fee category in `declared_category` (one of `COMMERCIAL`, `EDUCATIONAL`, `NEWS_MEDIA`, or `OTHER`), and an optional `organization` that defaults to absent. A freshly registered requester has an `outstanding_balance_cents` initialized to 0; this is a computed running total, never set directly. An officer is registered with a `full_name` and a unique, non-empty `badge_id`, plus an optional `can_invoke_glomar` flag that defaults to false and governs whether that officer may later refuse to confirm or deny the existence of records. An appeal authority is registered with a `full_name` and a unique, non-empty `badge_id`. A third-party submitter is registered with a `company_name` and a `contact_email` that must be non-empty and unique; this address is where Reverse-FOIA notices are directed.

### 3.2. Intake and Perfection

A request enters the system through submission. The submitter of the request — either the requester themselves or an officer acting on their behalf — provides the `requester_id` of the person on whose behalf it is filed, a non-empty `subject_description` of the records sought, and a `received_at` instant which the agency logs as the official receipt date and to which the working-day clock will later be anchored. The submission may also carry an `expedited` flag indicating that a compelling need for expedited processing was invoked (defaulting to false) and a `fee_waiver_requested` flag indicating that a public-interest fee waiver was sought (defaulting to false). A newly submitted request begins with its lifecycle `status` set to `SUBMITTED` and immediately gets a first audit event of type `SUBMITTED`. At creation the request's `fee_payment_status` is `NONE` and its parallel deadline dimension is `RUNNING`. The request list may be filtered by `requester_id`, by `assigned_officer_id`, or by `status`; each of the appeal and objection entities likewise carries its own lifecycle `status` field surfaced on the resource.

Perfection is the intake-completeness gate, performed by an officer against a request that is still in `SUBMITTED`. The request must reasonably describe the records sought, which the system enforces by requiring `subject_description` to be non-empty. When an officer perfects the request, they supply the agency's `fee_category` for it (again one of `COMMERCIAL`, `EDUCATIONAL`, `NEWS_MEDIA`, or `OTHER`); this agency-assigned category may differ from the requester's `declared_category` if the officer recategorizes. Perfection advances the request from `SUBMITTED` to `PERFECTED`, creates the request's processing deadline with a `base_due_at` of the receipt instant plus 20 working days and an `effective_due_at` computed from it, sets the deadline dimension to `RUNNING`, and appends a `PERFECTED` audit event. The 20-working-day clock formally starts here. Operations that require a perfected request but find it still `SUBMITTED` are rejected with `ERR_VALIDATION_NOT_PERFECTED`.

A request may be withdrawn by its owning requester at any point before a determination is reached — that is, while it is in `SUBMITTED`, `PERFECTED`, `PROCESSING`, or `AWAITING_PAYMENT`. Withdrawal moves the request to the terminal `WITHDRAWN` state, sets the deadline dimension to `MET` to reflect that no further obligation remains, and appends a determination audit event noting the withdrawal.

### 3.3. Assignment, Records, and Exemptions

Once perfected, a request is assigned for processing by an officer. Assignment requires the request to be in `PERFECTED`, advances it to `PROCESSING`, records the acting officer's identifier as `assigned_officer_id`, and appends an `ASSIGNED` audit event. Only while a request is in `PROCESSING` may its officer log responsive records, set their dispositions, and assert exemptions.

A responsive record is logged under a request with a short `title` and a `page_count` of at least 1. If the record contains a third party's confidential business information, the officer marks `contains_submitter_info` true (it defaults to false) and must supply the `submitter_id` of the business that originally provided it; a record flagged as containing submitter information without an accompanying `submitter_id`, or a downstream objection whose `submitter_id` does not equal the record's `submitter_id`, is rejected with `ERR_SUBMITTER_MISMATCH`. A new record starts with a `disposition` of `PENDING`.

Exemptions are the statutory bases for withholding. An exemption is asserted under a request with an `applies_to_kind` of either `RECORD` or `REQUEST`, an `exemption_code`, and a non-empty `justification`. The `exemption_code` must be one of the nine statutory codes `B1`, `B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `B8`, or `B9`; anything outside that set — or a request-level exemption whose code is not one of `B1` or `B7` — is rejected with `ERR_INVALID_EXEMPTION_CODE`. A record-scoped exemption names the `record_id` it cites; a request-scoped exemption (used for the Glomar path) leaves `record_id` absent, since it is asserted against the very question of whether records exist rather than against any specific record.

Reviewing a record sets its disposition while the parent request is in `PROCESSING`. An officer may move a record from `PENDING` to `RELEASABLE` only when no exemption with `applies_to_kind` `RECORD` cites that record. A record moves from `PENDING` to `REDACTED` or to `WITHHELD` only when at least one exemption with `applies_to_kind` `RECORD` cites it; an attempt to redact or withhold a record that no exemption cites is rejected with `ERR_EXEMPTION_REQUIRED`. The disposition supplied in the review body must therefore be consistent with the exemptions on file. Dispositions remain mutable until a determination is issued, and a remand resets them all to `PENDING`.

### 3.4. Fees, Waivers, and Payment

When an officer prepares a fee estimate for a processing request, they submit the professional `search_hours`, the document `review_hours`, and the count of `billable_pages` eligible for duplication charges (each non-negative), together with `expected_request_version` to guard against acting on a stale view of the request. Recording the estimate runs the tiered fee calculation, sets the estimate's `assessed_fee_cents`, recomputes the requester's `outstanding_balance_cents`, advances the request's `version` by one, and appends a `FEE_ASSESSED` audit event.

The tiered calculation works in integer cents and keys on the parent request's `fee_category`. Search time is billed per quarter-hour: the search hours are multiplied by four and rounded up to a whole number of quarter-hours, and review time is converted the same way. The search component is that number of search quarter-hours multiplied by the search rate of 1000 cents per quarter-hour (forty dollars per hour); the review component is the review quarter-hours multiplied by the review rate of 1000 cents per quarter-hour; the duplication component, before any free allotment, is the billable pages multiplied by 10 cents per page. Each of these three components is rounded half up to whole cents on its own. The categories then differ:

- For a `COMMERCIAL` request, all three components apply with no free allotment, and the assessed fee is the sum of the rounded search, review, and duplication components.
- For an `EDUCATIONAL` or `NEWS_MEDIA` request, only duplication is charged: there is no search or review charge, and the first 100 pages are free. The chargeable pages are the billable pages less 100, but never below zero, and the assessed fee is those chargeable pages multiplied by 10 cents per page, rounded half up.
- For an `OTHER` (public, individual, or non-commercial) request, there is no review charge; the first 2 hours of search time are free and the first 100 pages are free. The free search allotment is 2 hours expressed as quarter-hours (2 multiplied by 4); the chargeable search quarter-hours are the total search quarter-hours less that free allotment, never below zero, and the search component is those chargeable quarter-hours multiplied by 1000 cents per quarter-hour, rounded half up. The chargeable pages are the billable pages less 100, never below zero, and the duplication component is those pages multiplied by 10 cents per page, rounded half up. The assessed fee is the sum of those two rounded components.

If the request's fee waiver has been granted, the assessed fee is forced to 0 regardless of the tiered computation. After the fee is assessed, the system marks the estimate as requiring advance payment exactly when the assessed fee is strictly greater than the advance-payment threshold of 25000 cents (250 dollars). A waived estimate sets the request's `fee_payment_status` to `WAIVED`; otherwise the status becomes `DUE`.

The advance-payment threshold is what decides whether the clock pauses. If the resulting estimate requires advance payment — its `requires_advance_payment` is true — and no waiver was granted, the request moves from `PROCESSING` to `AWAITING_PAYMENT`, the deadline dimension becomes `TOLLED`, an advance-payment tolling window opens (freezing the operative deadline), and both a `FEE_ASSESSED` and a `TOLLED` audit event are appended. If instead the estimate is at or below the threshold, or a waiver was granted, the request stays in `PROCESSING`, the deadline dimension is unchanged, and no tolling occurs — only a `FEE_ASSESSED` event is appended. A single current fee estimate is maintained per request; recording a new estimate replaces the prior one.

A public-interest fee waiver is adjudicated by an officer against the request and likewise carries `expected_request_version`. The officer asserts four boolean findings: `f_public_understanding`, `f_not_commercial_interest`, `f_meaningful_contribution`, and `f_ability_to_disseminate`. Each finding contributes its weight when true and nothing when false; the weights are 0.40 for public understanding, 0.30 for non-commercial interest, 0.20 for meaningful contribution, and 0.10 for ability to disseminate. The score is 100 multiplied by the weighted sum of the four findings, rounded half up to an integer in the range 0 through 100. The waiver is granted when the score is at least 70 (the threshold is inclusive). A successful adjudication sets `fee_waiver_granted` accordingly and advances the request's `version` by one. A commercial requester is statutorily ineligible: when the request's `fee_category` is `COMMERCIAL`, the waiver cannot be granted regardless of score, and the attempt is rejected with `ERR_WAIVER_INELIGIBLE_COMMERCIAL`.

When a request is awaiting payment, its owning requester pays the assessed advance fee. The payment body carries `amount_cents`, which must equal the request's currently assessed fee due; a payment whose amount does not match the assessed fee is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`, as partial payments are not accepted. A valid payment requires the request to be in `AWAITING_PAYMENT` with a `fee_payment_status` of `DUE`; it sets `fee_payment_status` to `PAID`, returns the request to `PROCESSING`, recomputes the requester's `outstanding_balance_cents`, sets the deadline dimension back to `RUNNING`, closes the advance-payment tolling window by adding the working days that elapsed during it to the deadline's `tolled_working_days`, and appends a `RESUMED` audit event.

A requester's `outstanding_balance_cents` is the exact sum, with no rounding, of the assessed fee of the current fee estimate of each of that requester's requests whose `fee_payment_status` is `DUE`. Requests whose payment status is `PAID`, `WAIVED`, or `NONE` contribute nothing to the sum. This balance is recomputed on every fee assessment and on every payment.

### 3.5. Tolling, Extension, and the Deadline Outcome

The processing deadline carries a `base_due_at`, the working days added by an extension in `extension_days_added`, the cumulative paused working days in `tolled_working_days`, and the operative `effective_due_at`. The operative deadline is the base deadline advanced by the extension days plus the tolled working days, all counted in working days. A tolling window opens when the deadline dimension becomes `TOLLED` and closes when processing resumes; the tolled working days accumulate the count of working days strictly between the window's open and its close, counting the open day but not the close day, and multiple windows sum.

An officer may apply a single unusual-circumstances extension to a processing request. The extension is permitted only when no extension has yet been applied — that is, when `extension_days_added` is still 0. Applying it sets `extension_days_added` to 10 working days, recomputes `effective_due_at`, sets the deadline dimension to `EXTENDED`, and appends an `EXTENDED` audit event; the request remains in `PROCESSING`. A second extension attempt is rejected with `ERR_EXTENSION_ALREADY_USED`.

The deadline outcome is judged at the moment a determination is issued. The deadline dimension becomes `MET` when the determination instant is at or before the operative `effective_due_at` (the boundary is inclusive of that final instant) and `MISSED` otherwise. Because the deadline anchors on `received_at` and resolves at whole-day granularity, the test-driving clock is used to simulate the passage of working days deterministically.

### 3.6. Determinations and the Glomar Response

A determination resolves a processing request into a final outcome and is OCC-guarded: the officer supplies `expected_request_version`, and a mismatch with the request's current `version` is rejected with `ERR_STALE_REQUEST_VERSION`. The outcome is derived entirely from the dispositions of the request's records. A determination produces a full grant, transitioning the request from `PROCESSING` to `GRANTED`, when every responsive record is `RELEASABLE`. It produces a partial grant, transitioning to `PARTIALLY_GRANTED`, when at least one record is `REDACTED` or `RELEASABLE` and at least one record is `REDACTED` or `WITHHELD` — that is, a genuine mix of disclosure and withholding. It produces a full denial, transitioning to `DENIED`, when every record is `WITHHELD`. In both the partial-grant and the full-denial cases, every record that is `REDACTED` or `WITHHELD` must be backed by at least one exemption with `applies_to_kind` `RECORD` citing that record; a determination that would withhold or redact an uncited record is rejected with `ERR_EXEMPTION_REQUIRED`. Across all determination branches, no record flagged with `contains_submitter_info` true may be released while its objection is still `NOTICED` or `OBJECTED`; such a determination is rejected with `ERR_REVERSE_FOIA_PENDING`. Every successful determination increments the request's `version` by one, sets the deadline dimension to `MET` or `MISSED` per the deadline outcome rule, and appends a `DETERMINATION` audit event describing the outcome.

The Glomar response is a separate path by which the agency refuses to confirm or deny that any records exist. Invoking it is OCC-guarded by `expected_request_version` and requires the request to be in `PROCESSING`. The acting officer must be cleared to invoke Glomar — that is, their `can_invoke_glomar` must be true — or the attempt is rejected with `ERR_GLOMAR_NOT_AUTHORIZED`. Because the agency is neither confirming nor denying existence, no responsive record may have been logged for the request, and there must be exactly one exemption with `applies_to_kind` `REQUEST` whose `exemption_code` is either `B1` or `B7`; if records have been logged or that single request-level B1/B7 exemption is not present, the attempt is rejected with `ERR_GLOMAR_PRECONDITION`. A successful Glomar transitions the request from `PROCESSING` to `GLOMAR_INVOKED`, sets `glomar_exemption_basis` to the request-level exemption's code, increments the request's `version` by one, judges the deadline outcome as `MET` or `MISSED`, and appends a `GLOMAR` audit event.

### 3.7. Appeals and Remand

A requester may appeal a determination. An appeal is filed by the owning requester against a request and carries the `appellant_id` (which must equal the request's `requester_id`), a non-empty `grounds`, and a `filed_at` instant. An appeal may only be filed against a request that has reached a determination state — `GRANTED`, `PARTIALLY_GRANTED`, `DENIED`, or `GLOMAR_INVOKED`; filing against a request in any other state is rejected with `ERR_NOT_APPEALABLE`. The appeal must be filed within 90 calendar days of the determination: when the interval from the determination to `filed_at` exceeds 90 calendar days, the filing is rejected with `ERR_APPEAL_WINDOW_CLOSED`. A filed appeal begins in `FILED` status and appends an `APPEAL_FILED` audit event on the request.

An appeal authority takes up a filed appeal, which advances it from `FILED` to `UNDER_REVIEW` and records the acting authority's identifier as `assigned_authority_id`. Segregation of duties is preserved structurally: officers and appeal authorities are disjoint roles, so the authority reviewing the appeal is never the officer who issued the determination. From `UNDER_REVIEW`, the authority decides the appeal by supplying a `decision`, and the three decisions are treated with equal force:

- An `AFFIRM` decision moves the appeal to `AFFIRMED`; the original determination stands and the request remains in its determination state. An `APPEAL_DECIDED` audit event noting the affirmance is appended.
- A `REVERSE` decision moves the appeal to `REVERSED` and cascades to the underlying case: every responsive record on the request is set to `RELEASABLE` and the request's status is set to `GRANTED` to reflect the ordered full release. An `APPEAL_DECIDED` audit event noting the reversal and full release is appended.
- A `REMAND` decision moves the appeal to `REMANDED` and triggers the request's remand reset.

The remand reset is the deepest cascade in the system. When an appeal on a request that is in `DENIED` or `PARTIALLY_GRANTED` is remanded, the request reopens to `PROCESSING`, every one of its responsive records is reset to `PENDING`, the deadline dimension returns to `RUNNING`, and an `APPEAL_DECIDED` audit event noting that the case was remanded and reopened for reprocessing is appended. The case can then be re-reviewed and re-determined exactly as a fresh processing request would be, which makes the lifecycle cyclic: a remand turns a determination-state request back into a working case.

### 3.8. Reverse FOIA: Third-Party Objections

When a located record contains a third party's confidential business information, that business is given a chance to object before disclosure. An officer opens a Reverse-FOIA notice against such a record, supplying the `submitter_id` of the originating business (which must equal the record's own `submitter_id`) and the submitter's stated basis in a non-empty `objection_text` (typically asserting exemption B4 for confidential commercial information). Opening the notice records the `notice_sent_at` instant, starts the objection in `NOTICED` status, and appends a `REVERSE_NOTICE` audit event on the record's request.

From `NOTICED`, the submitter named on the objection may formally object, advancing it from `NOTICED` to `OBJECTED` and appending a reverse-notice audit event on the request. Only the submitter whose identifier matches the objection's `submitter_id` may take this action. The officer then resolves an objected matter by supplying a `resolution`. A `SUSTAIN` resolution moves the objection from `OBJECTED` to `SUSTAINED`, sets the linked record's disposition to `WITHHELD`, and creates a record-scoped exemption with code `B4` citing that record so the withheld record has the citation it requires; a `REVERSE_DECIDED` audit event noting the sustained objection is appended. An `OVERRULE` resolution moves the objection from `OBJECTED` to `OVERRULED`, which lifts the Reverse-FOIA gate so the linked record becomes eligible to be made releasable, and appends a `REVERSE_DECIDED` audit event permitting disclosure.

If the submitter never responds, the officer may let the notice lapse. Lapsing requires the objection to still be `NOTICED` and requires that the present moment be at or after the notice instant plus 10 calendar days (the reverse-notice window). Lapsing moves the objection from `NOTICED` to `NO_RESPONSE`, lifts the Reverse-FOIA gate so the linked record becomes eligible for release on the ground that no timely objection was made, and appends a `REVERSE_DECIDED` audit event. Throughout, the Reverse-FOIA gate means a submitter-info record cannot be made releasable, and cannot be released by a determination, while its objection is still `NOTICED` or `OBJECTED`; such an attempt is rejected with `ERR_REVERSE_FOIA_PENDING`.

### 3.9. Inspection Logistics: Reading Rooms and Review Stations

The system manages two distinct kinds of physical inspection space, each registered with a `name` and each governed by its own conflict geometry. A reading room is where requesters inspect released records; it is registered with a `capacity` of at least 1, meaning the maximum number of inspectors it can hold at any one instant. A review station is a secure single-occupancy terminal where an officer works; it is registered with a `buffer_minutes` cleanup gap of at least 0 minutes that must separate consecutive bookings on it.

A reading-room booking names the `room_id`, the `request_id` whose released records are being inspected, a `starts_at` instant, and an `ends_at` instant that must be strictly after `starts_at`. Reading-room bookings use half-open intervals [`starts_at`, `ends_at`) and aggregate-capacity semantics: at any instant covered by the proposed booking, the count of existing bookings on that room whose half-open interval contains that instant must stay below the room's capacity. The new booking is rejected when, at some instant it covers, the count of existing bookings already active there is at or above capacity — that is, the room is already full at some instant the new booking would occupy. Such a rejection carries `ERR_ROOM_AT_CAPACITY`. Because the intervals are half-open, two bookings that merely touch at an endpoint (one ending exactly when the next begins) never conflict, so adjacency is always permitted regardless of capacity.

A review-station booking names the `station_id`, the `request_id` whose records the officer reviews, a `starts_at` instant, and an `ends_at` instant strictly after `starts_at`. Review-station bookings use closed intervals [`starts_at`, `ends_at`] and single-occupancy-with-buffer semantics. A new booking is rejected when it falls within the station's buffer of any existing booking on it — concretely, when the new start is at or before an existing booking's end plus the buffer minutes and that existing booking's start is at or before the new end plus the buffer minutes. The rejection carries `ERR_STATION_BUFFER_CONFLICT`. Unlike the reading room, here adjacency is rejected: when two closed intervals merely touch at an endpoint they share that instant, and a non-negative buffer demands a gap, so a booking that begins exactly when another ends conflicts.

### 3.10. The Audit Trail and the Test-Driving Clock

Every request accumulates an append-only audit trail. Each `AuditEvent` records its `event_type` — drawn from `SUBMITTED`, `PERFECTED`, `ASSIGNED`, `FEE_ASSESSED`, `EXTENDED`, `TOLLED`, `RESUMED`, `DETERMINATION`, `GLOMAR`, `APPEAL_FILED`, `APPEAL_DECIDED`, `REVERSE_NOTICE`, and `REVERSE_DECIDED` — a human-readable `detail`, and the `actor_role` responsible, which is one of `Requester`, `FoiaOfficer`, `AppealAuthority`, `Submitter`, or `system`. Events are never edited once appended; the trail is read in creation order.

Because so many rules turn on the passage of working days (deadlines), calendar days (the 90-day appeal window and the 10-day reverse-notice window), the system exposes an administrative test-driving capability that sets the server's notion of "now" to a supplied instant via the `to_iso8601` field. This capability does not model any business event; it exists solely so that deadline, appeal-window, and reverse-notice arithmetic can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection (registering an actor, submitting a request, logging a record, asserting an exemption, filing an appeal, opening an objection, or creating a booking) return a `201 Created` status code. Operations that modify an existing resource — every lifecycle transition, fee computation, payment, determination, and decision — return a `200 OK` status code, as do all retrieval operations.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/requesters` | Register a requester | Requester, FoiaOfficer |
| GET | `/requesters/{id}` | Fetch a requester (includes computed balance) | Requester, FoiaOfficer |
| POST | `/officers` | Register a FOIA officer | FoiaOfficer |
| POST | `/appeal-authorities` | Register an appeal authority | FoiaOfficer |
| POST | `/submitters` | Register a third-party submitter | FoiaOfficer |
| POST | `/requests` | Submit a FOIA request | Requester, FoiaOfficer |
| GET | `/requests/{id}` | Fetch a request | Requester, FoiaOfficer, AppealAuthority |
| GET | `/requests` | List requests (filterable by requester, officer, status) | Requester, FoiaOfficer, AppealAuthority |
| POST | `/requests/{id}/perfect` | Perfect the request, assign fee category, start the clock | FoiaOfficer |
| POST | `/requests/{id}/assign` | Assign the request to the acting officer | FoiaOfficer |
| POST | `/requests/{id}/extend` | Apply the single 10-working-day extension | FoiaOfficer |
| POST | `/requests/{id}/withdraw` | Requester withdraws the request | Requester |
| POST | `/requests/{id}/records` | Log a responsive record | FoiaOfficer |
| GET | `/requests/{id}/records` | List responsive records for a request | Requester, FoiaOfficer, AppealAuthority |
| GET | `/records/{id}` | Fetch a responsive record | Requester, FoiaOfficer, AppealAuthority |
| GET | `/records` | List records (filterable by submitter, request) | Requester, FoiaOfficer, AppealAuthority |
| POST | `/records/{id}/review` | Set a record's disposition | FoiaOfficer |
| POST | `/requests/{id}/exemptions` | Assert an exemption (record or request/Glomar) | FoiaOfficer |
| GET | `/requests/{id}/exemptions` | List exemptions for a request | Requester, FoiaOfficer, AppealAuthority |
| GET | `/exemptions/{id}` | Fetch a single exemption | Requester, FoiaOfficer, AppealAuthority |
| GET | `/exemptions` | List exemptions (filterable by record, request) | Requester, FoiaOfficer, AppealAuthority |
| POST | `/requests/{id}/fee-estimate` | Compute and record the tiered fee estimate | FoiaOfficer |
| GET | `/requests/{id}/fee-estimate` | Fetch the current fee estimate | Requester, FoiaOfficer, AppealAuthority |
| POST | `/requests/{id}/fee-waiver` | Adjudicate a public-interest fee waiver | FoiaOfficer |
| POST | `/requests/{id}/payment` | Requester pays the assessed advance fee | Requester |
| GET | `/requests/{id}/deadline` | Fetch the processing deadline | Requester, FoiaOfficer, AppealAuthority |
| POST | `/requests/{id}/determination` | Issue the determination (OCC-guarded) | FoiaOfficer |
| POST | `/requests/{id}/glomar` | Invoke a Glomar response (OCC-guarded) | FoiaOfficer |
| POST | `/requests/{id}/appeals` | File an administrative appeal | Requester |
| GET | `/appeals/{id}` | Fetch an appeal | Requester, FoiaOfficer, AppealAuthority |
| GET | `/requests/{id}/appeals` | List appeals for a request | Requester, FoiaOfficer, AppealAuthority |
| GET | `/appeals` | List appeals (filterable by appellant, authority, request) | Requester, FoiaOfficer, AppealAuthority |
| POST | `/appeals/{id}/assign` | Appeal authority takes up the appeal | AppealAuthority |
| POST | `/appeals/{id}/decide` | Appeal authority decides (AFFIRM/REVERSE/REMAND) | AppealAuthority |
| POST | `/records/{id}/objection` | Open a Reverse-FOIA notice/objection | FoiaOfficer |
| GET | `/objections/{id}` | Fetch a Reverse-FOIA objection | Requester, FoiaOfficer, AppealAuthority, Submitter |
| GET | `/objections` | List objections (filterable by record, submitter) | Requester, FoiaOfficer, AppealAuthority, Submitter |
| POST | `/objections/{id}/object` | Submitter formally objects | Submitter |
| POST | `/objections/{id}/resolve` | Officer resolves (SUSTAIN/OVERRULE) | FoiaOfficer |
| POST | `/objections/{id}/lapse` | Officer marks a notice lapsed after the window | FoiaOfficer |
| POST | `/reading-rooms` | Register a reading room | FoiaOfficer |
| GET | `/reading-rooms/{id}` | Fetch a reading room | Requester, FoiaOfficer, AppealAuthority |
| POST | `/review-stations` | Register a secure review station | FoiaOfficer |
| GET | `/review-stations/{id}` | Fetch a review station | FoiaOfficer, AppealAuthority |
| POST | `/reading-rooms/{id}/bookings` | Book a reading-room inspection slot | Requester, FoiaOfficer |
| GET | `/reading-rooms/{id}/bookings` | List bookings for a reading room | Requester, FoiaOfficer, AppealAuthority |
| GET | `/reading-room-bookings/{id}` | Fetch a single reading-room booking | Requester, FoiaOfficer, AppealAuthority |
| GET | `/reading-room-bookings` | List reading-room bookings (filterable by request, room) | Requester, FoiaOfficer, AppealAuthority |
| POST | `/review-stations/{id}/bookings` | Book a review-station slot | FoiaOfficer |
| GET | `/review-stations/{id}/bookings` | List bookings for a review station | FoiaOfficer, AppealAuthority |
| GET | `/review-station-bookings/{id}` | Fetch a single review-station booking | FoiaOfficer, AppealAuthority |
| GET | `/review-station-bookings` | List review-station bookings (filterable by request, station) | FoiaOfficer, AppealAuthority |
| GET | `/requests/{id}/audit-events` | List the append-only audit trail for a request | Requester, FoiaOfficer, AppealAuthority |
| POST | `/_clock/set_current_utc` | Set the server's notion of "now" (test-driving) | FoiaOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_REQUEST_VERSION` | 412 |
| `ERR_GLOMAR_NOT_AUTHORIZED` | 403 |
| `ERR_GLOMAR_PRECONDITION` | 409 |
| `ERR_EXEMPTION_REQUIRED` | 409 |
| `ERR_REVERSE_FOIA_PENDING` | 409 |
| `ERR_INVALID_EXEMPTION_CODE` | 422 |
| `ERR_EXTENSION_ALREADY_USED` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_NOT_APPEALABLE` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_WAIVER_INELIGIBLE_COMMERCIAL` | 409 |
| `ERR_SUBMITTER_MISMATCH` | 422 |
| `ERR_VALIDATION_NOT_PERFECTED` | 409 |
| `ERR_ROOM_AT_CAPACITY` | 409 |
| `ERR_STATION_BUFFER_CONFLICT` | 409 |
