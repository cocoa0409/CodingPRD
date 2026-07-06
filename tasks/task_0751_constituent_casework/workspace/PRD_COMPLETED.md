# Constituent Casework API — Product Requirements Document

## 1. Introduction

Legislative offices live and die by responsiveness. A single representative's office may field thousands of constituent inquiries a year — immigration holds, stalled benefits, housing disputes, tax questions — and each one carries an implicit promise that a human being will follow up within a reasonable window. This document specifies the Constituent Casework API, the system of record that a legislative office uses to intake those inquiries, route them to caseworkers, refer them to external agencies, track them against service-level commitments, and ultimately answer them.

The API is deliberately broad because casework does not happen in isolation. The same office that works a housing case also runs town-hall events, sends newsletters to consenting constituents, and must honor privacy requests to erase a person's data on demand. These concerns interlock: a privacy purge must unwind a constituent's open cases, their agency referrals, and their event registrations in a single atomic sweep; a service-level clock must pause while the office waits on the constituent or an outside agency and resume when work restarts. The specification below treats each of these as a first-class workflow with precise, testable rules.

Throughout, the system relies on a **logical clock** rather than wall-clock time so that deadlines, pause accounting, and analytics windows are reproducible. Every timestamp the system writes — intake time, triage time, pause markers, resolution time — is drawn from this clock, and all service-level arithmetic is expressed in whole hours against it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request (with a single exception noted below) must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed and name a known role, but that role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes four roles, spelled exactly as follows: `OfficeAdmin`, `Caseworker`, `Constituent`, and `Anonymous`.

- `OfficeAdmin` is the legislative office administrator. It is a superset of `Caseworker` for all casework operations and additionally owns every configuration surface — creating representatives, agencies, response templates, venues, events, and newsletters — plus privacy purges and the logical-clock control. When `X-User-Role` is `OfficeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `assignee_staff_id` on a `Case` when that operator triages the case) but never compares it to any entity's `id`.
- `Caseworker` is office staff who triage, work, refer, and resolve cases. When `X-User-Role` is `Caseworker`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it (again, as `assignee_staff_id` at triage) but does not compare it to any entity's `id`.
- `Constituent` is a person acting strictly on their own records. When `X-User-Role` is `Constituent`, `X-User-ID` is the `id` of the acting `Constituent` entity; ownership checks on any resource that references a constituent compare that resource's constituent foreign key to `X-User-ID`. Concretely, when a `Constituent` files or withdraws a case, replies to an information request, purges or edits their own record, registers for or cancels an event registration, or reads one of their own resources, the system requires `X-User-ID` to equal the owning constituent's `id`; a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403).
- `Anonymous` is the unauthenticated self-service surface. It exists solely so a new constituent can self-register. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is not compared to any entity's `id`. Self-registration is the one operation exempt from the authentication check above; every other endpoint requires a recognized, authenticated role.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied value below 1 is clamped up to 1 and a value above 100 is clamped down to 100. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative offset is clamped to 0. A `limit` or `offset` that cannot be parsed as an integer silently falls back to its default (10 and 0 respectively) rather than being rejected.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by ascending creation sequence (the order in which the records were minted).

Every list-based response includes the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Representative`, `Constituent`, `Agency`, `ResponseTemplate`, `Case`, `AgencyReferral`, `Venue`, `Event`, `EventRegistration`, and `NewsletterCampaign` — carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created (drawn from the logical clock; see §2.5).
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at `1` on creation and increments by one on every mutation. It is the anchor for optimistic concurrency control (§2.9).

All ten entities in this system carry the full set above, including `updated_at` and `version`. Whenever a computed or derived field on a resource changes as a side effect of some operation — for example, a ledger counter such as `open_referral_count`, `registered_count`, or `upcoming_event_count`, or a case's accumulated pause total — that change is a mutation of the owning resource: it refreshes `updated_at` and increments `version` on that resource.

### 2.5. The Logical Clock

The system does not read wall-clock time. Instead it maintains a single **logical clock** that governs every timestamp it writes (`created_at`, `updated_at`, `triaged_at`, `paused_since`, `resolved_at`, `closed_at`, `withdrawn_at`, `sent_at`, `registered_at`) and every piece of time arithmetic (service-level deadlines, pause accumulation, breach evaluation, and analytics trailing windows). At process startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly advanced it stays at that default — it never falls back to real time. An `OfficeAdmin` may advance the clock to a supplied instant; this test-driving capability accepts a single `to_iso8601` field naming the new current UTC instant and sets the clock to it. All duration math in this document ("in hours", "trailing window") is measured against this clock.

### 2.6. Validation Ordering and Referential Integrity

When a single request could fail several checks, the system evaluates them in a fixed priority order and returns the error for the first check that fails. The order is:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401). This applies to every endpoint except self-registration acting as `Anonymous`.
2. **Authorization** — the role is permitted the operation per the role matrix, else `ERR_UNAUTHORIZED` (403). Applies to all.
3. **Ownership** — for an entity-backed `Constituent` acting on an owned resource, `X-User-ID` equals the resource owner's constituent id, else `ERR_FORBIDDEN` (403). Applies to a constituent filing a case, replying to an information request, withdrawing a case, purging or editing their own record, registering for or cancelling an event registration, and reading their own constituent, case, or registration.
4. **Request shape** — the body carries all required fields with valid types and enum values, else `ERR_INVALID_REQUEST` (400). Applies to all writes.
5. **Time-range validity** — where an interval is supplied, `start_at` is strictly before `end_at`, else `ERR_INVALID_TIME_RANGE` (422). Applies to scheduling and rescheduling an event.
6. **Existence** — every referenced resource, both the path id and any body foreign key, exists; references are validated left-to-right in the order they appear, and the first missing one yields its type-specific not-found error (404) — `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_CONSTITUENT_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, or `ERR_NEWSLETTER_NOT_FOUND`. Applies to every endpoint that references an id.
7. **State** — the target resource is in a state that permits the requested transition (per the workflow rules in §3), else the entity-specific conflict error (409): `ERR_CASE_INVALID_STATE`, `ERR_REFERRAL_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`, or `ERR_REGISTRATION_INVALID_STATE`. Applies to all transition and action endpoints.

Beyond this backbone, several domain-specific checks sit at lower priority and are described where their workflow lives: data-sharing consent on referral creation (`ERR_CONSENT_REQUIRED`, 403); the referenced constituent being `ACTIVE` rather than `PURGED` (`ERR_CONSTITUENT_PURGED`, 409); the referenced agency being `ACTIVE` (`ERR_AGENCY_INACTIVE`, 409); template active-and-matching at triage (`ERR_TEMPLATE_MISMATCH`, 422); duplicate event registration (`ERR_DUPLICATE_REGISTRATION`, 409); venue overlap (`ERR_VENUE_CONFLICT`, 409); representative overlap (`ERR_REPRESENTATIVE_CONFLICT`, 409); event capacity and venue-capacity ceiling (`ERR_EVENT_FULL`, 409); and the optimistic-concurrency stale-version check on rescheduling (`ERR_STALE_VERSION`, 412). The relative priority among these is: consent before purged-constituent, before agency-inactive, before template-mismatch, before duplicate-registration, before venue-conflict, before representative-conflict, before event-full, before stale-version — i.e. they are evaluated in that sequence after the existence and state checks above.

For nested reads that carry more than one identifier in the path — a case's referrals, an event's registrations, a representative's newsletters — the outer path id is validated before the inner one, and the first identifier that does not resolve produces its own not-found error.

### 2.7. Cascading Consistency and Ledger Counters

Several resources carry **ledger counters** that must always equal a live count of related rows. `Agency.open_referral_count` is the number of that agency's referrals currently in `SENT` status. `Event.registered_count` is the number of that event's registrations currently in `REGISTERED` status. `Constituent.upcoming_event_count` is the number of that constituent's registrations currently in `REGISTERED` status. Each counter is incremented and decremented exactly at the transitions described in §3, and each such adjustment is a mutation of the owning resource (refreshing `updated_at`, incrementing `version`).

Consistency is **immediate and atomic**: when one operation triggers a chain of downstream effects, the entire chain is applied inside the triggering request, and the response reflects the fully settled state. Two cascades are transitive and deserve special care. A constituent purge is a depth-three sweep — the purge withdraws the constituent's open cases, each withdrawn case recalls that case's open referrals, and each recalled referral that had been sent decrements its agency's counter. An event cancellation is a depth-two sweep — cancelling the event cancels each of its live registrations, and each cancelled registration decrements both the event's `registered_count` and that registrant's `upcoming_event_count`. The precise membership of each cascade is specified in §3.

### 2.8. Service-Level Precision and Rounding

All service-level arithmetic is performed against the logical clock and expressed in hours. Timestamps are serialized as ISO 8601 UTC with three fractional digits, and datetime offsets in the deadline calculations are applied as whole hours. Two derived quantities are decimal: a case's effective response window and its elapsed-time figures are each rounded to exactly two decimal places using the round-half-up convention. The breach determination compares the rounded net elapsed value against the effective window. Recurring-issue index scores are likewise carried to two decimal places, round-half-up, with per-case contributions rounded before they are summed and the running total rounded again afterward (see §3.8). Newsletter costs are computed and stored in whole integer cents.

### 2.9. Optimistic Concurrency Control

Rescheduling an event is the one operation guarded by optimistic concurrency control. Because rescheduling from the `SCHEDULED` lifecycle is a legitimate repeat operation — a newly supplied time simply supersedes the prior one — a stale client view cannot be caught by any state precondition, so the system reduces it to a version check on the parent `Event`. A reschedule request must carry `expected_event_version`, and this field is mandatory for that operation. If `expected_event_version` does not equal the target event's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), which prevents a client from overwriting a schedule it has not observed. No other endpoint in this system accepts or requires a client-supplied version field.

### 2.10. Privacy and Data Redaction

A constituent has the right to be erased. When a purge is performed, the constituent's `full_name`, `email`, and `address` are overwritten with the literal string `REDACTED`, and their `phone` is likewise overwritten with `REDACTED` when a phone value is present. The constituent's `status` moves to `PURGED`, and their open casework and event activity are unwound atomically (§3.2). A purged constituent is a dead end for new work: any operation that would reference a `PURGED` constituent — filing a new case for them, or registering them for an event — is rejected with `ERR_CONSTITUENT_PURGED`.

## 3. Business Logic & Workflows

### 3.1. Foundational Configuration Records

Before casework can flow, an `OfficeAdmin` establishes the reference data the rest of the system leans on. A **representative** record captures the elected official's `full_name`, the `chamber` they sit in (either `HOUSE` or `SENATE`), the `district_name` they serve such as "CA-12", the two-letter `state_code`, and the legislative office's contact `office_email`. Representatives are the anchor to which constituents, cases, events, and newsletters all attach.

An **agency** is an external body the office refers cases to, such as a state motor-vehicle department. It carries a `name`, a `jurisdiction`, and a `status` that is either `ACTIVE` or `INACTIVE` and defaults to `ACTIVE` when omitted at creation; only `ACTIVE` agencies accept referrals. Each agency also exposes the read-only `open_referral_count` ledger, which starts at zero.

A **response template** encodes the office's service-level commitment for a category of casework. It names the `category` it applies to — one of `IMMIGRATION`, `HEALTHCARE`, `HOUSING`, `TAX`, `BENEFITS`, or `OTHER` — carries the boilerplate `body_template` used when a matching case is answered, and declares a `response_window_hours`, the base service window in hours, which must be greater than zero. Its `active` flag defaults to true, and only active templates may be selected during triage.

A **venue** is a physical location where a town-hall may be held. It has a `name`, a `capacity` (the seating ceiling, which must be at least zero and is the upper bound for any event held there), and an optional `address`.

### 3.2. Constituent Registration and the Privacy Lifecycle

A **constituent** enters the system either by self-registering (acting as `Anonymous`) or by being registered by staff. Registration supplies the `representative_id` of the district they belong to, their `full_name`, `email`, and `address`; a `phone` is optional and defaults to null. Two consent flags are captured at registration and both default to false when omitted: `contact_consent`, which governs whether the constituent may be included as a newsletter recipient, and `data_sharing_consent`, which governs whether their case data may be shared with an external agency. On creation the constituent's `status` defaults to `ACTIVE` and their `upcoming_event_count` ledger starts at zero. A constituent — or an `OfficeAdmin` on their behalf — may later revise their contact details and either consent flag; each of `full_name`, `email`, `address`, `phone`, `contact_consent`, and `data_sharing_consent` is individually updatable.

Staff can look up a single constituent, and can list constituents filtered by their `representative_id` or by `status`, which serves as the reverse lookup from a representative to their constituents. A constituent reading their own record must be the owner of that record.

The privacy purge is the system's most consequential cascade, and either an `OfficeAdmin` or the owning `Constituent` may invoke it. It is permitted only while the constituent's `status` is `ACTIVE`; when the actor is the constituent themselves, `X-User-ID` must equal that constituent's `id`. The purge does the following atomically. First, it redacts the constituent's personally identifying fields as described in §2.10 and sets `status` to `PURGED`. Second (cascade hop one), every one of that constituent's cases whose `status` is any of `NEW`, `IN_PROGRESS`, `AWAITING_CONSTITUENT`, or `AWAITING_AGENCY` transitions to `WITHDRAWN`, stamping `withdrawn_at` with the current clock value. Third (cascade hop two, driven by each case that just withdrew), every referral of such a case whose `status` is `DRAFT` or `SENT` transitions to `RECALLED` with its `closed_reason` set to `RECALLED`. Fourth (cascade hop three, driven only by each referral that was `SENT` when recalled), that referral's agency has its `open_referral_count` decremented by one; a referral recalled from `DRAFT` changes no counter because a draft was never counted. In parallel with the case sweep, every one of the constituent's event registrations still in `REGISTERED` status transitions to `CANCELLED`, and each such cancellation decrements both the associated event's `registered_count` and the constituent's own `upcoming_event_count` by one.

### 3.3. Case Intake and Triage

An inquiry becomes a **case** at intake. A constituent (filing their own inquiry), a `Caseworker`, or an `OfficeAdmin` files it by supplying the `constituent_id` of the filer, a `subject` line, a free-text `description`, and a `category` drawn from `IMMIGRATION`, `HEALTHCARE`, `HOUSING`, `TAX`, `BENEFITS`, or `OTHER`. When a constituent files their own case, `X-User-ID` must equal the supplied `constituent_id`. Intake refuses a `PURGED` constituent with `ERR_CONSTITUENT_PURGED`. On success the case is created in `status` `NEW` with `priority` `NORMAL`; its `representative_id` is copied from the filing constituent's own `representative_id` rather than supplied by the client. Intake also computes a provisional deadline: `provisional_due_at` is the case's `created_at` advanced by the default window for its category, where the default window in hours is 168 for `IMMIGRATION`, 120 for `HEALTHCARE`, 120 for `HOUSING`, 72 for `TAX`, 96 for `BENEFITS`, and 168 for `OTHER`. The provisional computation ignores any template, priority, or surcharge — it is purely category-driven from intake time.

**Triage** is the routing step, performed by a `Caseworker` or `OfficeAdmin`, and it moves the case from `NEW` to `IN_PROGRESS`. It is only permitted when the case is in `NEW`; otherwise `ERR_CASE_INVALID_STATE`. The request names a `template_id` to apply, the `priority` to assign (one of `LOW`, `NORMAL`, `HIGH`, or `URGENT`), and the `assignee_staff_id` of the caseworker taking ownership. The referenced template must exist, be active, and have a `category` equal to the case's own category; if the template is inactive or its category does not match, the request is rejected with `ERR_TEMPLATE_MISMATCH`. The case's constituent must still be `ACTIVE` at triage. On success the system records `assigned_template_id` (the chosen template's id, retained for audit rather than as a persisted relationship), `assignee_staff_id`, and the assigned `priority`; copies the template's `response_window_hours` onto the case's own `response_window_hours`; stamps `triaged_at` with the current clock; and computes the final deadline.

The final deadline uses the template window scaled by priority plus a category surcharge, capped at a ceiling. Concretely, `effective_window_hours` is the smaller of two quantities: the case's `response_window_hours` multiplied by the priority multiplier and then increased by the category surcharge, versus the hard ceiling of 720 hours. The priority multiplier is 1.5 for `LOW`, 1.0 for `NORMAL`, 0.5 for `HIGH`, and 0.25 for `URGENT`. The category surcharge in hours is 24 for `IMMIGRATION`, 12 for `HEALTHCARE`, 12 for `HOUSING`, and 0 for `TAX`, `BENEFITS`, and `OTHER`. That is, the system first multiplies the window by the multiplier, then adds the surcharge, then takes the lesser of that sum and 720, and rounds the result to two decimal places using round-half-up. The resulting `effective_window_hours` is stored, and `final_due_at` is set to `triaged_at` advanced by `effective_window_hours` hours. Before triage, `effective_window_hours`, `final_due_at`, `response_window_hours`, `assigned_template_id`, and `assignee_staff_id` are all null.

### 3.4. Working a Case: Information Requests and the Pausing Clock

Once `IN_PROGRESS`, a case accrues elapsed time against its service window, but that clock can be paused. A `Caseworker` or `OfficeAdmin` can request more information from the constituent, which moves the case from `IN_PROGRESS` to `AWAITING_CONSTITUENT` and may include an optional `message`. The only precondition is that the case is `IN_PROGRESS`; the side effect is to set `paused_since` to the current clock value, freezing the service clock. The constituent supplies the requested information with their own optional `message`, which moves the case from `AWAITING_CONSTITUENT` back to `IN_PROGRESS`; this is a constituent-only action requiring `X-User-ID` to equal the case's `constituent_id`, and it is only valid from `AWAITING_CONSTITUENT`. On resume, the number of hours between the current clock and `paused_since` is added to the case's running `cumulative_paused_hours`, and `paused_since` is cleared back to null so the clock runs again. This `IN_PROGRESS ↔ AWAITING_CONSTITUENT` loop may repeat any number of times, each hop adding to the accumulated pause total.

The elapsed-time figures a reader sees on a case are recomputed on every read against the current clock (and frozen once the case is answered — see §3.6). The **gross** figure, `gross_elapsed_hours`, is the number of hours between a reference end point and `triaged_at`, where the reference end point is `resolved_at` when the case is `RESOLVED` or `CLOSED` and the current clock otherwise. The **net** figure, `net_elapsed_hours`, subtracts from the gross figure both the case's accumulated `cumulative_paused_hours` and any currently-open pause — that open pause being the hours between the current clock and `paused_since` when the case is presently in `AWAITING_CONSTITUENT` or `AWAITING_AGENCY`, and zero otherwise. Both figures are carried to two decimal places, round-half-up. A case is `breached` when its rounded `net_elapsed_hours` is strictly greater than its `effective_window_hours`; before triage the case is never breached and both elapsed figures read zero.

### 3.5. Agency Referrals and the Send Fork

When a case needs an outside body, a `Caseworker` or `OfficeAdmin` refers it to an agency. Referral creation is only valid from `IN_PROGRESS` and requires two safety gates: the case's constituent must have `data_sharing_consent` set to true, else `ERR_CONSENT_REQUIRED`; and the referenced agency must be `ACTIVE`, else `ERR_AGENCY_INACTIVE`. The request supplies the `agency_id` and optional `referral_notes`. On success the case moves from `IN_PROGRESS` to `AWAITING_AGENCY`, its `paused_since` is set to the current clock (pausing the service clock exactly as an information request does), and a new **agency referral** is created linking the case's `case_id` and the `agency_id`, starting in `status` `DRAFT`. A draft referral is not yet counted against the agency.

Sending is a separate step. A `Caseworker` or `OfficeAdmin` sends a `DRAFT` referral, which moves it to `SENT`; this is permitted only when the referral is `DRAFT`, its parent case is in `AWAITING_AGENCY`, and the referenced agency is still `ACTIVE` (else `ERR_AGENCY_INACTIVE`). Sending stamps `sent_at` with the current clock and increments the agency's `open_referral_count` by one.

A sent referral then forks. In the resolve branch, a `Caseworker` or `OfficeAdmin` records that the agency resolved the matter, moving the referral from `SENT` to `RESOLVED`; the request may carry a `response_summary` supplied by the agency, `closed_reason` is set to `RESOLVED`, the agency's `open_referral_count` is decremented by one, and the parent case is returned from `AWAITING_AGENCY` to `IN_PROGRESS` with its `last_agency_outcome` set to `RESOLVED`, resuming the service clock (accumulating the open pause into `cumulative_paused_hours` and clearing `paused_since`). In the reject branch, the operator records that the agency rejected the referral, moving it from `SENT` to `REJECTED` with an optional `reason`; `closed_reason` is set to `REJECTED`, the agency's `open_referral_count` is decremented by one, and the parent case is likewise returned to `IN_PROGRESS` and its clock resumed — but here `last_agency_outcome` is set to `REJECTED` and the case's `reject_count` is additionally incremented by one. The two branches are symmetric in structure but deliberately divergent in their bookkeeping: only the reject branch advances `reject_count` and only it stamps `REJECTED` as the outcome. Both branches are valid only from `SENT`; an attempt from any other state yields `ERR_REFERRAL_INVALID_STATE`. A referral's `response_summary` is null until an agency supplies it, and its `closed_reason` — one of `RESOLVED`, `REJECTED`, `RECALLED`, or `CASE_CLOSED` — is null while the referral remains active.

Referrals also leave the active set by system action rather than operator action. When a case is withdrawn or its constituent purged, any referral of that case in `DRAFT` or `SENT` is recalled: it moves to `RECALLED` with `closed_reason` `RECALLED`, and the agency's `open_referral_count` is decremented by one only when the referral had been `SENT` (a `DRAFT` recall touches no counter). When a resolved case is closed, any lingering referral of that case in `DRAFT` or `SENT` moves to `CLOSED` with `closed_reason` `CASE_CLOSED`, again decrementing the agency counter only when the prior status was `SENT`. Referrals of a case can be listed as a nested reverse lookup on `case_id`, and referrals can also be listed globally filtered by `agency_id`, `case_id`, or `status`.

### 3.6. Resolving, Closing, and Withdrawing Cases

A `Caseworker` or `OfficeAdmin` answers the constituent and resolves the case, moving it from `IN_PROGRESS` to `RESOLVED` with an optional `response_body`. This is valid only from `IN_PROGRESS`; it stamps `resolved_at` with the current clock and freezes the elapsed figures (`gross_elapsed_hours` and `net_elapsed_hours`) against `resolved_at` so they no longer advance on subsequent reads.

Closing is an `OfficeAdmin`-only finalization, valid only from `RESOLVED`, that moves the case to `CLOSED` and stamps `closed_at`. As described in §3.5, closing cascades to any of the case's referrals still in `DRAFT` or `SENT`, moving each to `CLOSED` and decrementing the relevant agency counter for those that were `SENT`.

Withdrawal is the constituent's escape hatch. Acting on their own case (with `X-User-ID` equal to the case's `constituent_id`), a `Constituent` may withdraw an inquiry from any non-terminal state — that is, whenever the case's `status` is `NEW`, `IN_PROGRESS`, `AWAITING_CONSTITUENT`, or `AWAITING_AGENCY` — moving it to `WITHDRAWN` and stamping `withdrawn_at` with the current clock. Withdrawal cascades exactly like the recall step of a purge: every referral of the case in `DRAFT` or `SENT` moves to `RECALLED` with `closed_reason` `RECALLED`, decrementing the agency's `open_referral_count` by one for those that were `SENT`. `RESOLVED` and `CLOSED` are terminal outcomes that cannot be withdrawn; `WITHDRAWN` and `CLOSED` are the two terminal states of a case. Staff read a single case (which triggers the on-read recomputation of gross, net, and breach) and list or route cases filtered by `constituent_id`, `representative_id`, `status`, or `category`, the reverse lookup from a constituent or a representative to their cases. A constituent reading a case must own it.

### 3.7. Town-Hall Events and Registrations

An `OfficeAdmin` schedules a **town-hall event** into a venue, supplying the hosting `representative_id`, the `venue_id`, a `title`, an inclusive `start_at`, an exclusive `end_at`, and a registration `capacity` (at least zero). Scheduling enforces several rules. The time range must be valid — `start_at` strictly before `end_at`, else `ERR_INVALID_TIME_RANGE`. The event's `capacity` must not exceed the venue's `capacity` at creation, else `ERR_EVENT_FULL`. Two overlap rules protect against double-booking. The venue rule expands the new half-open interval by a fixed venue buffer of `VENUE_BUFFER_MINUTES` (30) minutes on both sides and rejects the event with `ERR_VENUE_CONFLICT` if that buffered interval overlaps any other `SCHEDULED` event at the same venue. The representative rule uses the raw half-open interval with no buffer and rejects with `ERR_REPRESENTATIVE_CONFLICT` if it overlaps any other `SCHEDULED` event hosted by the same representative; because the interval is half-open, two events that meet exactly end-to-start do not conflict. A newly scheduled event begins with `lifecycle_status` `SCHEDULED`, `registration_status` `CLOSED`, and `registered_count` zero. The `lifecycle_status` (either `SCHEDULED` or `CANCELLED`) and the `registration_status` (one of `CLOSED`, `OPEN`, or `FULL`) evolve independently of one another.

An `OfficeAdmin` opens registration on a scheduled event whose registration is currently `CLOSED`, which sets `registration_status` to `OPEN` — or immediately to `FULL` when `registered_count` is already at least the event's `capacity`, which covers the edge case of a zero-capacity event. The admin may reschedule a scheduled event under optimistic concurrency (§2.9): the request carries the mandatory `expected_event_version` plus a new `start_at`, `end_at`, and optionally a new `venue_id`. Rescheduling is valid only while `lifecycle_status` is `SCHEDULED`, requires `expected_event_version` to match the event's current `version` (else `ERR_STALE_VERSION`), re-runs the same time-range, venue-buffer, representative-overlap, and capacity-ceiling checks as creation, and on success updates `start_at`, `end_at`, and `venue_id` (when supplied) and increments the event's `version` by one.

Cancelling an event is an `OfficeAdmin` action valid only while `lifecycle_status` is `SCHEDULED`. It sets `lifecycle_status` to `CANCELLED` and `registration_status` to `CLOSED`, then cascades: every registration of the event still in `REGISTERED` status moves to `CANCELLED`, and each such cancellation decrements the event's `registered_count` by one and the affected constituent's `upcoming_event_count` by one.

A constituent (registering themselves, with `X-User-ID` equal to the supplied `constituent_id`) or an `OfficeAdmin` registers for an event by supplying the `constituent_id`. Registration is admitted only when the event's `lifecycle_status` is `SCHEDULED` and its `registration_status` is not `CLOSED` (the state gate rejects with `ERR_EVENT_INVALID_STATE` only when the event's `lifecycle_status` is not `SCHEDULED` or its `registration_status` is `CLOSED`; an event whose `registration_status` is `FULL` passes this state gate and is instead stopped by the capacity check below), the constituent is `ACTIVE`, there is no existing `REGISTERED` registration for the same event-and-constituent pair (else `ERR_DUPLICATE_REGISTRATION`), and the event's `registered_count` is strictly less than its `capacity` (else `ERR_EVENT_FULL`). The duplicate check is evaluated before the capacity check. On success an **event registration** is created in `status` `REGISTERED` with `registered_at` stamped from the clock; the event's `registered_count` is incremented by one, and if that brings it up to `capacity` the `registration_status` flips to `FULL`; and the constituent's `upcoming_event_count` is incremented by one.

A registration is cancelled by its owning `Constituent` (with `X-User-ID` equal to the registration's `constituent_id`) or by an `OfficeAdmin`, valid only while the registration is `REGISTERED`. Cancelling moves it to `CANCELLED`, decrements the event's `registered_count` by one — and if the event's `registration_status` was `FULL` and its `lifecycle_status` is still `SCHEDULED`, reopens it to `OPEN` — and decrements the constituent's `upcoming_event_count` by one. An already-cancelled registration cannot be cancelled again (`ERR_REGISTRATION_INVALID_STATE`). Registrations of an event are listed as a nested reverse lookup on `event_id`, and registrations can be listed globally filtered by `constituent_id`, `event_id`, or `status` (a `Constituent` calling the global list sees only their own registrations, regardless of the supplied filters). Events themselves are listed filtered by `representative_id`, `venue_id`, or `lifecycle_status`.

### 3.8. Newsletters and Recurring-Issue Analytics

An `OfficeAdmin` composes and sends a **newsletter campaign** on behalf of a representative, supplying a `subject`, a `body`, and a `page_count` (at least one printed page). Sending is immediate: the campaign is created already in `status` `SENT`, and at send time the system computes its reach and cost. The `recipient_count` is the number of constituents belonging to the sending representative (matching on `representative_id`) whose `status` is `ACTIVE` and whose `contact_consent` is true. The `send_cost_cents` is the `recipient_count` multiplied by the sum of a base postage charge of 55 cents plus a per-page printing charge of 8 cents times the campaign's `page_count`; the result is expressed in whole cents. A representative's newsletters can be listed as a reverse lookup on `representative_id`, and a single campaign can be fetched by its id.

The **recurring-issue index** summarizes casework pressure for a representative. It is computed for a required `representative_id` and an optional `category`, in one of two variants selected by an optional `variant` parameter (any `variant` value other than `RAW` or `TREND` is rejected with `ERR_INVALID_REQUEST`), and returns the `representative_id`, `category` (echoed as null when the filter is omitted), `variant`, the computed `index`, and the `case_count` of the pool it scored. In every variant, withdrawn cases are excluded from the pool, and each case contributes a weight based on its priority: 0.5 for `LOW`, 1.0 for `NORMAL`, 2.0 for `HIGH`, and 3.5 for `URGENT`.

In the `RAW` variant, which is the default, the pool is all-time: every case for the given representative (optionally narrowed to the given category) whose `status` is not `WITHDRAWN`. Each case's priority weight is rounded to two decimal places, those rounded contributions are summed, and the total is rounded again to two decimal places (round-half-up), yielding the `index`. In the `TREND` variant, the pool is first restricted to a trailing window: a cutoff is computed as the current clock minus `window_days` days (defaulting to 30 days when `window_days` is omitted; a supplied `window_days` that cannot be parsed as an integer is rejected with `ERR_INVALID_REQUEST`), and only cases whose `created_at` is at or after that cutoff remain, on top of the same representative, optional-category, and not-`WITHDRAWN` filters. In `TREND`, each surviving case contributes its priority weight multiplied by a recency bonus of 1.25; each such per-case contribution is rounded to two decimal places first, then all contributions are summed, then the total is rounded again — this round-then-sum-then-round order is required. The `case_count` returned is the size of whichever pool the selected variant used.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. The logical-clock control returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | OfficeAdmin |
| POST | `/representatives` | Create a representative record | OfficeAdmin |
| GET | `/representatives/{id}` | Fetch a representative | OfficeAdmin, Caseworker |
| POST | `/constituents` | Register a constituent (self-service or by staff) | Anonymous, OfficeAdmin |
| GET | `/constituents/{id}` | Fetch a constituent (own record for Constituent) | Constituent, Caseworker, OfficeAdmin |
| GET | `/constituents` | List constituents, filtered by representative or status | Caseworker, OfficeAdmin |
| PATCH | `/constituents/{id}` | Update contact info and consent flags | Constituent, OfficeAdmin |
| POST | `/constituents/{id}/purge` | Privacy purge with cascade | Constituent, OfficeAdmin |
| POST | `/agencies` | Create an external agency | OfficeAdmin |
| GET | `/agencies/{id}` | Fetch an agency | Caseworker, OfficeAdmin |
| POST | `/response-templates` | Create a response template | OfficeAdmin |
| GET | `/response-templates/{id}` | Fetch a response template | Caseworker, OfficeAdmin |
| POST | `/cases` | Intake a new casework inquiry | Constituent, Caseworker, OfficeAdmin |
| GET | `/cases/{id}` | Fetch a case (recomputes elapsed/breach) | Constituent, Caseworker, OfficeAdmin |
| GET | `/cases` | List/route cases | Caseworker, OfficeAdmin |
| POST | `/cases/{id}/triage` | Triage: assign template, priority, assignee | Caseworker, OfficeAdmin |
| POST | `/cases/{id}/request-info` | Request info; pause SLA clock | Caseworker, OfficeAdmin |
| POST | `/cases/{id}/constituent-reply` | Constituent replies; resume SLA clock | Constituent |
| POST | `/cases/{id}/respond` | Send response and resolve the case | Caseworker, OfficeAdmin |
| POST | `/cases/{id}/close` | Close a resolved case | OfficeAdmin |
| POST | `/cases/{id}/withdraw` | Withdraw an inquiry | Constituent |
| POST | `/cases/{id}/referrals` | Refer a case to an agency | Caseworker, OfficeAdmin |
| GET | `/cases/{id}/referrals` | List a case's referrals | Caseworker, OfficeAdmin |
| GET | `/agency-referrals/{id}` | Fetch a referral | Caseworker, OfficeAdmin |
| GET | `/agency-referrals` | List referrals | Caseworker, OfficeAdmin |
| POST | `/agency-referrals/{id}/send` | Send a draft referral | Caseworker, OfficeAdmin |
| POST | `/agency-referrals/{id}/resolve` | Record agency resolution | Caseworker, OfficeAdmin |
| POST | `/agency-referrals/{id}/reject` | Record agency rejection | Caseworker, OfficeAdmin |
| GET | `/analytics/recurring-issues` | Recurring-issue index for a representative | Caseworker, OfficeAdmin |
| POST | `/venues` | Create a venue | OfficeAdmin |
| GET | `/venues/{id}` | Fetch a venue | OfficeAdmin, Caseworker |
| POST | `/events` | Schedule a town-hall | OfficeAdmin |
| GET | `/events/{id}` | Fetch an event | Constituent, Caseworker, OfficeAdmin |
| GET | `/events` | List events | Constituent, Caseworker, OfficeAdmin |
| POST | `/events/{id}/reschedule` | Reschedule an event under OCC | OfficeAdmin |
| POST | `/events/{id}/open-registration` | Open registration | OfficeAdmin |
| POST | `/events/{id}/cancel` | Cancel an event with cascade | OfficeAdmin |
| POST | `/events/{id}/registrations` | Register a constituent for an event | Constituent, OfficeAdmin |
| GET | `/events/{id}/registrations` | List an event's registrations | Caseworker, OfficeAdmin |
| GET | `/event-registrations/{id}` | Fetch a registration | Constituent, OfficeAdmin |
| GET | `/event-registrations` | List registrations | Constituent, OfficeAdmin |
| POST | `/event-registrations/{id}/cancel` | Cancel a registration | Constituent, OfficeAdmin |
| POST | `/representatives/{id}/newsletters` | Compose and send a newsletter | OfficeAdmin |
| GET | `/representatives/{id}/newsletters` | List a representative's newsletters | OfficeAdmin |
| GET | `/newsletters/{id}` | Fetch a newsletter campaign | OfficeAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_REPRESENTATIVE_NOT_FOUND` | 404 |
| `ERR_CONSTITUENT_NOT_FOUND` | 404 |
| `ERR_AGENCY_NOT_FOUND` | 404 |
| `ERR_TEMPLATE_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_NEWSLETTER_NOT_FOUND` | 404 |
| `ERR_CASE_INVALID_STATE` | 409 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_EVENT_INVALID_STATE` | 409 |
| `ERR_REGISTRATION_INVALID_STATE` | 409 |
| `ERR_CONSTITUENT_PURGED` | 409 |
| `ERR_CONSENT_REQUIRED` | 403 |
| `ERR_AGENCY_INACTIVE` | 409 |
| `ERR_TEMPLATE_MISMATCH` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_VENUE_CONFLICT` | 409 |
| `ERR_REPRESENTATIVE_CONFLICT` | 409 |
| `ERR_EVENT_FULL` | 409 |
| `ERR_STALE_VERSION` | 412 |
