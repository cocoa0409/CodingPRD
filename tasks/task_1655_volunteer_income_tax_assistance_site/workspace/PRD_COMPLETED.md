# Vita Site Ops API — Product Requirements Document

## 1. Introduction

Every filing season, sponsoring organizations in the IRS Volunteer Income Tax Assistance (VITA) program open community sites where certified volunteers prepare tax returns free of charge for eligible taxpayers. Running such a site is an exercise in controlled compliance: volunteers must pass certification tests and keep them current, every return must survive an independent quality review before it is e-filed, work that falls outside program scope must be referred rather than attempted, and rejected transmissions must be followed up with the taxpayer and reworked within strict submission limits. This document specifies the API through which a sponsoring program and its sites manage that entire operation — from site onboarding and volunteer testing, through appointment scheduling, intake, preparation, quality review, transmission, and acknowledgement, to season statistics reporting and financial-capability add-on services.

The API serves five acting roles and is organized around a set of peer entities — sites, volunteers and their certifications, taxpayers, appointments, tax returns, refund allocations, e-file rejections, financial-service referrals, and sponsor reports — whose lifecycles interlock through explicit state machines, compliance gates, and cascading consistency rules. Two features of the platform shape every workflow: all time-dependent rules are evaluated against a controllable logical clock rather than the wall clock, and all money is represented as integer cents with deterministic rounding, so that refund estimates, final refund determinations, savings-match incentives, and sponsor-facing acceptance rates are reproducible to the cent.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. The system recognizes exactly five roles: `SiteCoordinator`, `Preparer`, `QualityReviewer`, `Screener`, and `SponsorAdmin`. A request that omits either header, presents an undeclared role, or — for an entity-backed role — presents an `X-User-ID` that does not reference an existing Volunteer is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401).

When `X-User-Role` is `SiteCoordinator`, `Preparer`, `QualityReviewer`, or `Screener`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a Volunteer compare the resource's foreign-key field to `X-User-ID`. Two actor-level rules ride on top of this binding. First, a `SiteCoordinator` acting on an operation addressed to a specific site must be a volunteer whose `is_coordinator` flag is true and whose `site_id` equals that site's `id`; otherwise the call is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). This own-site binding is enforced exactly on the site lifecycle transition, on report generation, and on report submission; every other operation that merely references a site — volunteer registration, certification recording, and volunteer activation or inactivation, taxpayer and appointment operations, return edits and lifecycle steps, allocation management, rejection follow-up, referral offers and advances, and report listing — checks the caller's role only, never the coordinator's home site or `is_coordinator` flag. Second, preparer-only lifecycle steps on a return compare `X-User-ID` against the return's `preparer_id`; a preparer attempting such a step on a return it does not own is rejected with `ERR_NOT_RETURN_OWNER` (HTTP 403). When `X-User-Role` is `SponsorAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.

Beyond identity, each role carries a distinct operational envelope. A `SiteCoordinator` is the volunteer leader of a site: it certifies, opens, suspends, and closes its own site, transmits e-files, records IRS acknowledgements, and generates and submits sponsor reports. A `Preparer` is a certified volunteer who opens returns from checked-in appointments and owns the returns it creates — its `X-User-ID` becomes the return's `preparer_id` — driving them through preparation, review submission, and rework, and managing their refund allocations. A `QualityReviewer` is an experienced certified volunteer who performs the mandatory quality review before e-file and handles e-file rejection follow-up; it must never review a return it prepared. A `Screener` is the intake volunteer who registers taxpayers, verifies photo IDs, schedules and checks in appointments, and maintains the intake document checklist. A `SponsorAdmin` is the sponsoring-program administrator who onboards sites and their first coordinators, acknowledges submitted reports, and drives the test clock. Any action attempted outside the caller's role envelope is rejected with `ERR_FORBIDDEN_ROLE`.

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
- Datetime values in request bodies may be supplied in any ISO 8601 form, with any offset or none (an absent offset is read as UTC); responses echo every datetime field in canonical UTC with three fractional digits and a trailing `Z`, whatever form was supplied.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — an out-of-range value is clamped to the nearest bound rather than rejected, and a non-integer value falls back to the default. The `offset` parameter specifies how many items to skip and defaults to 0, with negative values clamped to 0 and non-integer values falling back to the default. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order, with resources sharing a creation timestamp ordered by insertion sequence, and the reverse-reach listing views described in §4 (a site's volunteers, a site's reports, a volunteer's certification attempts, a return's allocations, rejections, and financial referrals) follow the same ordering. Supplied filters combine conjunctively; `total_count` counts every matching resource before the page is sliced, and `has_more` is true exactly when matching resources remain beyond the returned page. The two top-level list views accept optional filters: the appointments list filters by `site_id`, `taxpayer_id`, `volunteer_id`, and `status`, and the returns list filters by `taxpayer_id`, `site_id`, `appointment_id`, `preparer_id`, `reviewer_id`, and `status`. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in the system — Site, Volunteer, Certification, Taxpayer, Appointment, TaxReturn, RefundAllocation, EfileRejection, SiteReport, and FinancialServiceReferral — carries a uniform set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T09:15:00.123Z`) recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments on every mutation of the resource, including cascade-driven and system-driven mutations.

A mutation is any change to a resource's stored properties, whether it originates in a client request or in a server-side cascade; recording a certification attempt, for instance, mutates the volunteer it belongs to and therefore bumps the volunteer's `version`. These properties give every entity a consistent audit trail and a stable handle for optimistic concurrency.

### 2.5. The Logical Clock

All time-dependent rules in the system — appointment past-start checks, no-show eligibility, the season-window check performed when a site opens, and the rejection follow-up overdue computation — are evaluated against a server-maintained logical clock, never against wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `SponsorAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; the response reports the new logical instant as `current_utc`. Features that compare against "the current logical time" anywhere in this document read this clock, and every timestamp carried on a resource — `created_at`, `updated_at`, `transmitted_at`, `follow_up_due_at`, `contacted_at`, `resolved_at`, `generated_at` — is stamped from this logical clock; the `api_request_timestamp` in the response envelope's `meta` is the only wall-clock reading in the system.

### 2.6. Money, Cents, and Rounding Discipline

All monetary values in the system — wages, other income, earned income, withholding, refunds, allocation amounts, and savings-match incentives — are represented as integer numbers of cents. Whenever a calculation multiplies a money amount by a rate, the product is rounded half-up to whole cents at the step where the multiplication occurs, before any subsequent minimum or maximum is taken; this holds for the provisional refund estimate, the final refund determination, and the tax-liability component alike. Rates reported back to the sponsoring program are expressed in basis points as integers, also rounded half-up. One calculation applies a deliberately different rounding discipline: the savings-match incentive floors each qualifying allocation line down to whole dollars before the per-line matches are summed, and only then applies its cap (§3.6). Counts and cent totals in sponsor reports are exact integers with no rounding.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only these two.

Editing a return's intake and preparation fields requires the request to carry `expected_return_version`, holding the `version` of the return the client last observed. If the return's current `version` has advanced beyond that value — because another writer has since edited the return — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the return before writing. Recording a certification attempt against a volunteer likewise requires `expected_volunteer_version`, holding the `version` of the volunteer the client last observed; a mismatch with the volunteer's current `version` is rejected with the same `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field. On both guarded operations the comparison runs after request-schema validation and before every state-legality and business precondition of the operation: a missing or ill-typed version field is a schema failure (`ERR_INVALID_REQUEST`), while a well-formed but outdated value fails with `ERR_STALE_VERSION` and masks all later checks.

### 2.8. Validation Order: The Gate Pipeline

Every request walks a fixed pipeline of validation tiers, and a failure in an earlier tier masks every later tier: the error a caller observes always comes from the earliest tier its request fails. The tiers, in evaluation order:

1. **Authentication**, on all endpoints: the `X-User-Role` and `X-User-ID` headers must be present, the role must be one of the five declared roles, and for the entity-backed roles the `X-User-ID` must reference an existing Volunteer — otherwise `ERR_MISSING_AUTH_HEADER` (HTTP 401).
2. **Authorization**, on all endpoints: the acting role must be permitted for the endpoint — checked immediately after authentication, before any resource is loaded — and the transition-level actor rules of §2.1 must hold: a `SiteCoordinator` acting outside its own site, or without `is_coordinator`, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), and a preparer-only transition attempted by a non-owner preparer is rejected with `ERR_NOT_RETURN_OWNER` (HTTP 403). Actor rules that compare the caller against a stored resource are evaluated once that resource is available: the coordinator own-site binding compares the acting volunteer's `site_id` against the site id named in the path — or, when submitting a report, against the `site_id` of the loaded report — so it runs before existence validation on site-addressed calls but after schema validation on report submission; return-ownership checks run after the return's existence check, before request-schema validation on return edits, and after request-schema validation on return state transitions and refund-allocation creation.
3. **Existence**, on all endpoints that reference resource ids: path- and body-referenced ids must exist, validated left-to-right in the order site, volunteer, taxpayer, appointment, tax return, allocation, rejection, report, referral — the first missing id yields `ERR_NOT_FOUND` (HTTP 404).
4. **Request schema**, on all endpoints: required fields must be present, types correct, enum values valid, unknown fields rejected, numeric bounds and fixed formats respected (station capacity and season goal of at least one, daily hours within 0–23 and 1–24, certification scores from 0 to 100, money fields and qualifying-children counts non-negative with qualifying children at most ten, allocation amounts of at least one cent, routing numbers of exactly nine digits), and conditionally required fields supplied — `review_notes` when failing a review, `rejection_code` and `rejection_text` when recording a rejection, `referral_reason` and `referral_destination` when referring, `withdrawal_reason` on an actor-driven withdrawal, `disbursement_confirmed` and `taxpayer_notified` when completing a return, and `resolution_note` when resolving a follow-up — otherwise `ERR_INVALID_REQUEST` (HTTP 400). The non-null `withholding_verified_cents` precondition for review submission is not part of this tier: it is a resource-state gate evaluated with the transition's business preconditions, after state legality (§3.5).
5. **State legality**, on every state-driving call, on identity verification, on rejection follow-up, on return edits, on allocation add and remove, and on appointment rescheduling: the requested transition must exist from the resource's current state — terminal states accept no transitions — and the editability windows must hold. A return's intake and preparation fields are editable only while the return is `INTAKE_STARTED` or `IN_PREPARATION`; allocations may be added or removed only while their return is `INTAKE_STARTED`, `IN_PREPARATION`, or `QR_PASSED`, so allocations stay editable right up until transmit; an appointment may be rescheduled only while `SCHEDULED`. Violations are rejected with `ERR_INVALID_TRANSITION` (HTTP 409).
6. **Compliance gates**, on return creation and on return lifecycle transitions, evaluated in a fixed sub-order: (a) the taxpayer's `identity_status` must be `VERIFIED` before a return is opened (`ERR_IDENTITY_NOT_VERIFIED`, HTTP 422); (b) the acting preparer must be `ACTIVE` and hold `CURRENT` passed `ETHICS` and `BASIC` certifications for season 2026, plus `ADVANCED` when `has_advanced_scope_items` is true (`ERR_VOLUNTEER_NOT_CERTIFIED`, HTTP 403); (c) the acting reviewer must be `ACTIVE` and hold `CURRENT` passed `INTAKE_QR` and `ADVANCED` certifications for season 2026 (`ERR_REVIEWER_NOT_CERTIFIED`, HTTP 403); (d) the reviewer must not be the return's preparer (`ERR_REVIEWER_IS_PREPARER`, HTTP 422); (e) the return must be in scope before it may enter preparation or review (`ERR_OUT_OF_SCOPE`, HTTP 422).
7. **Uniqueness and cardinality**, on taxpayer registration, volunteer registration, return creation, allocation creation, and appointment creation and rescheduling: a taxpayer's `ssn_token` must be unique across all taxpayers (`ERR_TAXPAYER_DUPLICATE_SSN`, HTTP 409); a volunteer's `email` must be unique across all volunteers (`ERR_INVALID_REQUEST`, HTTP 400); an appointment may originate at most one return (`ERR_APPOINTMENT_ALREADY_USED`, HTTP 409) — checked before the rule that a taxpayer may have at most one in-flight return per site (`ERR_OPEN_RETURN_EXISTS`, HTTP 409), so a call violating both surfaces `ERR_APPOINTMENT_ALREADY_USED`; a return may carry at most three refund allocations (`ERR_ALLOCATION_LIMIT`, HTTP 422); and the number of overlapping appointments at a site must remain below its `station_capacity` (`ERR_SITE_CAPACITY_FULL`, HTTP 409).
8. **Temporal rules**, on appointment creation and rescheduling and on report generation — and here the window rules run before the overlap exclusion: appointment window and duration violations surface as `ERR_OUTSIDE_SITE_WINDOW` (HTTP 422) before the volunteer double-booking exclusion surfaces as `ERR_APPOINTMENT_OVERLAP_VOLUNTEER` (HTTP 409); a report whose `period_end` is not strictly after its `period_start` is rejected with `ERR_REPORT_PERIOD_INVALID` (HTTP 422).
9. **Cross-entity state gates**, on appointment creation and lifecycle transitions, on return creation, and on return lifecycle transitions: creating an appointment requires the site to be `CERTIFIED` or `OPEN` (`ERR_SITE_NOT_OPEN`, HTTP 409) and the assigned volunteer to be `ACTIVE` (`ERR_VOLUNTEER_NOT_ACTIVE`, HTTP 409); check-in, return creation, and transmission each require the site to be `OPEN` (`ERR_SITE_NOT_OPEN`); opening a return requires the appointment to be `CHECKED_IN` (`ERR_APPOINTMENT_NOT_CHECKED_IN`, HTTP 409); and rework from `REJECTED` requires every e-file rejection of the return to be `RESOLVED` (`ERR_REJECTION_UNRESOLVED`, HTTP 409) with fewer than three transmissions recorded (`ERR_MAX_SUBMISSIONS_REACHED`, HTTP 409).
10. **Money conservation**, on transmission only: when the return's `refund_method` is `DIRECT_DEPOSIT`, its allocations must number between one and three and sum exactly to its `final_refund_cents` (`ERR_ALLOCATION_SUM_MISMATCH`, HTTP 422).

### 2.9. Nested Resource Retrieval

Whenever a request path or payload threads several resources together — a report generated under a site, an allocation written against a return, a follow-up recorded against a rejection — the system validates the existence of each referenced identifier in a strict left-to-right order: site first, then volunteer, taxpayer, appointment, tax return, allocation, rejection, report, and finally referral. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, and no later identifier is examined. Body-referenced identifiers — the `appointment_id` presented when opening a return, the `tax_return_id` presented when adding an allocation — participate in the same ordering discipline as path parameters.

### 2.10. Cascading State Consistency

When a resource undergoes a transition that strands dependent work — a site suspended mid-season, a volunteer inactivated, an appointment cancelled, a return referred or withdrawn — the server resolves the dependents automatically, without requiring explicit client requests on each affected resource. Every cascade step is an ordinary mutation of the resource it touches: it refreshes `updated_at` and increments `version` on that resource. The concrete cascade chains are specified alongside their triggers in §3 — the site-suspension cascade in §3.1, the volunteer-inactivation cascade in §3.2, the appointment-cancellation withdrawal in §3.3, and the referral-voiding invariant in §3.8. Because cascades mutate real resources, a client holding a stale `version` of a cascade-affected entity will discover it through the optimistic-concurrency rejection of §2.7 on its next guarded write.

## 3. Business Logic & Workflows

### 3.1. Site Onboarding, Season Certification, and Suspension

A `SponsorAdmin` onboards a new VITA site by supplying its `name`, its `sponsor_org`, its scheduling geometry, and its season target. The scheduling geometry comprises `station_capacity` — the maximum number of appointments whose time intervals may overlap at the site, at least one — plus the inclusive season bounds `season_start` and `season_end` and the daily operating window `daily_open_hour` (an hour from 0 to 23) through `daily_close_hour` (an hour from 1 to 24), where the open hour must be strictly earlier than the close hour, with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400). The season target `goal_returns`, also at least one, is the number of accepted returns the site aims to file. A newly created site's `status` field begins as `SETUP`. All lifecycle-driving calls in this system follow the same shape: the caller supplies a `to_status` naming the desired next state, and the server validates the transition against the resource's state machine.

From `SETUP`, a site is certified by its `SiteCoordinator` once the site has at least one volunteer whose `is_coordinator` flag is true and whose status is `ACTIVE`; without such a volunteer the certification attempt is rejected with `ERR_INVALID_TRANSITION`. Because volunteer activation is permitted while a site is still in `SETUP` (§3.2), the very first coordinator can bootstrap itself active and then certify the site. From `CERTIFIED`, the coordinator opens the site — but only while the current logical time falls within the season window from `season_start` through `season_end`, both bounds inclusive; an open attempted outside the season is rejected with `ERR_INVALID_TRANSITION`.

Suspending an `OPEN` site is always permitted and carries the system's deepest cascade, in three links. Link one: every appointment of the site in `SCHEDULED` or `CHECKED_IN` status is cancelled. Link two: each appointment cancelled by link one that originated a tax return still in `INTAKE_STARTED` causes that return to be withdrawn, with `withdrawal_reason` recorded as `SITE_SUSPENDED`. Link three: each return withdrawn by link two voids its financial-service referrals still in `OFFERED` or `ACCEPTED`, moving them to `VOID`. Re-opening a `SUSPENDED` site carries no preconditions.

Closing a site, from either `OPEN` or `SUSPENDED`, is guarded by an open-work check: the site must have no appointments in `SCHEDULED` or `CHECKED_IN`, and no tax returns in `INTAKE_STARTED`, `IN_PREPARATION`, `PENDING_QR`, `QR_FAILED`, `QR_PASSED`, `TRANSMITTED`, or `REJECTED`. Any such open work blocks closure with `ERR_SITE_HAS_OPEN_WORK`. `CLOSED` is terminal.

Throughout the season the site tracks its progress live: its `accepted_count` is the number of its tax returns currently in `ACCEPTED` or `COMPLETED` status, and its `goal_met` flag turns true once `accepted_count` reaches `goal_returns`.

### 3.2. Volunteer Registration, Testing, and Activation

Volunteers are registered against a home site by a `SiteCoordinator` or a `SponsorAdmin`, who supply the volunteer's `site_id`, `full_name`, and `email`, and may set `is_coordinator` (default false) to mark the volunteer as a leader of its site. The `email` must be unique across all volunteers; a collision is rejected with `ERR_INVALID_REQUEST`. Registration is permitted whatever the site's current status. A new volunteer begins in `REGISTERED`.

Certification is recorded as discrete test attempts against the volunteer. Recording an attempt — permitted to a `SiteCoordinator` or `SponsorAdmin`, whatever the volunteer's current status — takes a `test_type` (one of `ETHICS`, `INTAKE_QR`, `BASIC`, or `ADVANCED`), a `score` from 0 to 100, and the `tax_season` year the attempt is valid for (the current season is 2026). A score of at least 80 passes: the attempt's computed `passed` flag is true exactly when the score is 80 or higher. Each attempt's `attempt_number` is one plus the count of earlier attempts recorded for the same volunteer, test type, and season. The newest attempt for a given (volunteer, test type, season) triple becomes `CURRENT`, and every earlier attempt for that triple is moved to `SUPERSEDED`; each attempt row stays tied to its volunteer through `volunteer_id`. Because recording an attempt mutates the volunteer, the call is optimistic-concurrency guarded on the volunteer's `version` via `expected_volunteer_version` (§2.7), and a successful recording increments the volunteer's `version` by one.

Supersession carries a teeth: if the attempt just superseded was the volunteer's only `CURRENT` passed `ETHICS` certification for season 2026, and the newly recorded attempt did not pass, the volunteer immediately and automatically drops from `ACTIVE` to `INACTIVE`, triggering the same cancellation cascade as a manual inactivation.

Activation — from `REGISTERED` to `ACTIVE`, and again from `INACTIVE` back to `ACTIVE` — is performed by a `SiteCoordinator` or `SponsorAdmin` and requires the volunteer to hold a `CURRENT`, passed `ETHICS` certification for season 2026; without one, activation is rejected with `ERR_VOLUNTEER_NOT_CERTIFIED`. Activation is rejected with `ERR_INVALID_TRANSITION` when the volunteer's site is `CLOSED`, but it is expressly allowed while the site is still in `SETUP`, which is what lets the first coordinator bootstrap the site toward certification.

Inactivation, whether invoked manually or driven by the supersession rule above, cancels every appointment assigned to the volunteer that is still `SCHEDULED` — appointments already `CHECKED_IN` are left untouched — and each cancelled appointment that originated a return still in `INTAKE_STARTED` withdraws that return with `withdrawal_reason` recorded as `VOLUNTEER_INACTIVATED`, carrying the referral-voiding that accompanies every withdrawal (§3.8).

Two computed views summarize a volunteer's standing. `certified_test_types` lists the test types for which the volunteer currently holds a `CURRENT`, passed certification for season 2026, in the canonical order `ETHICS`, `INTAKE_QR`, `BASIC`, `ADVANCED`. `active_case_count` counts the volunteer's returns presently in `IN_PREPARATION`; its ebb and flow through the return lifecycle is detailed in §3.4 through §3.8.

### 3.3. Taxpayer Intake and Appointment Scheduling

Taxpayer registration is an intake duty shared by the `Screener` and the `SiteCoordinator`. Registering a taxpayer captures `full_name`, `ssn_token` — a tokenized stand-in for the Social Security number that must be unique across all taxpayers, with collisions rejected as `ERR_TAXPAYER_DUPLICATE_SSN` — and `phone`, with optional `email` (null when omitted) and `preferred_language` (one of `EN`, `ES`, or `OTHER`, defaulting to `EN`). A new taxpayer's `identity_status` begins as `UNVERIFIED`.

Before any return can be opened for a taxpayer, a `Screener` or `SiteCoordinator` must verify the taxpayer's photo ID. Verification supplies the `id_document_type` — one of `DRIVERS_LICENSE`, `PASSPORT`, `STATE_ID`, or `MILITARY_ID` — moves `identity_status` to `VERIFIED`, and records the document type on the taxpayer. `VERIFIED` is terminal: attempting identity verification on an already-verified taxpayer is rejected with `ERR_INVALID_TRANSITION`.

Appointment scheduling, again shared by `Screener` and `SiteCoordinator`, takes a payload naming the `site_id`, the `taxpayer_id`, the assigned `volunteer_id`, the visit's `purpose` (one of `INTAKE`, `PREPARATION`, or `FOLLOW_UP`), and the interval endpoints `start_at` and `end_at`. A new appointment begins as `SCHEDULED`. Two cross-entity gates apply at creation, per the pipeline of §2.8: the site must be `CERTIFIED` or `OPEN` (`ERR_SITE_NOT_OPEN`), and the assigned volunteer must be `ACTIVE` (`ERR_VOLUNTEER_NOT_ACTIVE`). The assigned volunteer need not belong to the appointment's site; no cross-site membership check applies.

The appointment's placement is then checked against the site's window rules, and every violation of these rules surfaces as `ERR_OUTSIDE_SITE_WINDOW`. The `start_at` must not lie in the past relative to the current logical time. The appointment must sit inside the season: `start_at` on or after `season_start`, and `end_at` on or before `season_end`. It must sit inside the daily operating window: the time-of-day of `start_at` at or after the open hour, and the time-of-day of `end_at` at or before the close hour. And its duration — `end_at` minus `start_at` — must be at least 15 minutes and no more than two hours.

Conflict geometry uses half-open intervals: an appointment occupies the interval from `start_at` inclusive to `end_at` exclusive, so two appointments where one ends exactly when the other begins do not overlap. The volunteer double-booking exclusion rejects the new appointment with `ERR_APPOINTMENT_OVERLAP_VOLUNTEER` when any existing appointment assigned to the same `volunteer_id`, in `SCHEDULED` or `CHECKED_IN` status, overlaps the new interval. The station-capacity ceiling counts the site's existing appointments in `SCHEDULED` or `CHECKED_IN` that overlap the new interval; when that count has already reached `station_capacity`, the appointment is rejected with `ERR_SITE_CAPACITY_FULL` — a count exactly one below capacity means the new appointment takes the site's last remaining slot. Per the pipeline of §2.8, the capacity ceiling is evaluated before the window rules, and the window rules before the volunteer exclusion.

Rescheduling is permitted only while the appointment is `SCHEDULED` (`ERR_INVALID_TRANSITION` otherwise). Changing an interval endpoint re-runs the capacity ceiling, then the window rules, then the volunteer double-booking exclusion; changing only the `volunteer_id` re-runs the capacity ceiling and the volunteer exclusion without re-running the window rules — in every case with the appointment being rescheduled excluded from its own overlap and capacity counts. Supplying a field with its current value changes nothing and re-runs no check; an edit that changes nothing still refreshes `updated_at` and increments `version`.

On the day of service, checking in an appointment — `SCHEDULED` to `CHECKED_IN` — requires the hosting site to be `OPEN` (`ERR_SITE_NOT_OPEN`). Completing a visit moves `CHECKED_IN` to `COMPLETED`. Marking an appointment `NO_SHOW` from `SCHEDULED` is allowed only once the current logical time has reached its `start_at`; an early no-show is rejected with `ERR_INVALID_TRANSITION`. Cancelling — from `SCHEDULED` or from `CHECKED_IN` — withdraws any return the appointment originated that is still in `INTAKE_STARTED`, recording `withdrawal_reason` as `APPOINTMENT_CANCELLED`. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are the appointment's terminal states.

### 3.4. Opening a Return: Documents, Scope, and the Intake Estimate

Once a taxpayer is checked in, a `Preparer` opens a return by supplying the originating `appointment_id`, the `tax_year` of the return, the `filing_status` (one of `SINGLE`, `MARRIED_JOINT`, `HEAD_OF_HOUSEHOLD`, or `MARRIED_SEPARATE`), and optionally `has_advanced_scope_items` (default false) and `out_of_scope_flags` (default empty). Opening is gated through the pipeline of §2.8: the taxpayer's `identity_status` must be `VERIFIED` (`ERR_IDENTITY_NOT_VERIFIED`); the acting preparer must be `ACTIVE` and hold `CURRENT` passed `ETHICS` and `BASIC` certifications for season 2026, plus `ADVANCED` when `has_advanced_scope_items` is true (`ERR_VOLUNTEER_NOT_CERTIFIED`); cardinality then forbids reusing an appointment that already originated a return (`ERR_APPOINTMENT_ALREADY_USED`) and forbids opening a second in-flight return for the same taxpayer at the same site — in-flight meaning any status other than `COMPLETED`, `REFERRED`, or `WITHDRAWN` (`ERR_OPEN_RETURN_EXISTS`) — evaluated in that order; and finally the appointment must be `CHECKED_IN` (`ERR_APPOINTMENT_NOT_CHECKED_IN`) and the site must be `OPEN` (`ERR_SITE_NOT_OPEN`).

At creation the return derives its context from the appointment: `taxpayer_id` and `site_id` are copied across, `preparer_id` is set to the acting preparer's `X-User-ID`, and the return begins in `INTAKE_STARTED`. Its `reviewer_id` stays null until the first quality review, `submission_count` and `qr_failure_count` start at zero, `reached_preparation` starts false, `transmitted_at`, `referral_reason`, `referral_destination`, `withdrawal_reason`, and `first_ack_outcome` all start null, and the provisional `estimated_refund_cents` is computed immediately — zero while all the money fields are at their default of zero.

While the return is `INTAKE_STARTED` or `IN_PREPARATION`, its intake and preparation fields may be edited by the `Screener`, the owning `Preparer`, or the `SiteCoordinator` — a `Preparer` attempting to edit a return it does not own is rejected with `ERR_NOT_RETURN_OWNER`, a check applied before the edit's schema validation — and editing against any other status is rejected with `ERR_INVALID_TRANSITION`. The editable surface comprises `documents_received` — any subset of `PHOTO_ID`, `SSN_CARD`, `W2`, `FORM_1099`, `PRIOR_YEAR_RETURN`, and `BANK_INFO`, starting empty — the `interview_confirmed` flag (false until the intake and interview sheet has been reviewed with the taxpayer), the money fields `wages_cents`, `other_income_cents`, `earned_income_cents`, `withholding_reported_cents`, and `withholding_verified_cents` (each at least zero when present, with `withholding_verified_cents` null until documents have been verified), `qualifying_children` (from 0 to 10, default 0), the `refund_method` (`PAPER_CHECK` by default, or `DIRECT_DEPOSIT`), and the scope fields `has_advanced_scope_items` and `out_of_scope_flags`; fields outside this surface — `filing_status`, `tax_year`, `appointment_id` — are not editable and are rejected as unknown fields. Each edit replaces every supplied field wholesale — a supplied `documents_received` list becomes the return's new checklist in full, with no merging. Every such edit must carry `expected_return_version` per §2.7, recomputes the return's `documents_complete`, `out_of_scope`, `out_of_scope_reasons`, and `estimated_refund_cents`, and increments the return's `version` by one — an edit that supplies no field beyond `expected_return_version` still refreshes `updated_at` and increments `version`.

Two computed flags govern whether the return may move forward. `documents_complete` is true exactly when `PHOTO_ID`, `SSN_CARD`, and `W2` are all present in `documents_received` and, whenever the `refund_method` is `DIRECT_DEPOSIT`, `BANK_INFO` is present as well. `out_of_scope` is true when `out_of_scope_flags` is non-empty — the recognized flags are `RENTAL_INCOME`, `BUSINESS_WITH_LOSS`, `FOREIGN_EARNED_INCOME`, and `CASUALTY_LOSS` — or when the `filing_status` is `MARRIED_SEPARATE`; `out_of_scope_reasons` then enumerates the flags, appending `FILING_STATUS_MFS` whenever the filing status is `MARRIED_SEPARATE`, whether or not flags are also present.

The provisional estimate shown at intake deliberately assumes zero tax liability and trusts self-reported withholding: `estimated_refund_cents` is the taxpayer-reported `withholding_reported_cents` plus an estimated earned-income credit equal to the lesser of 15 percent of `earned_income_cents` — the multiplication rounded half-up to whole cents — and $6,000. It is recomputed at creation and on every edit that touches `wages_cents`, `other_income_cents`, `earned_income_cents`, `withholding_reported_cents`, or `qualifying_children`, and it exists only to set expectations at intake; the binding determination happens at review submission (§3.5).

Beginning preparation — `INTAKE_STARTED` to `IN_PREPARATION` — is restricted to the return's owner: the acting preparer's `X-User-ID` must equal the return's `preparer_id` (`ERR_NOT_RETURN_OWNER`). It requires `documents_complete` to be true and `interview_confirmed` to be true (`ERR_DOCUMENTS_INCOMPLETE`), and the return must still be in scope (`ERR_OUT_OF_SCOPE`). On entry, `reached_preparation` flips to true and is never cleared, and the preparer's `active_case_count` increases by one.

### 3.5. Quality Review and the Final Refund Determination

Submitting for review — `IN_PREPARATION` to `PENDING_QR`, again owner-only (`ERR_NOT_RETURN_OWNER`) — demands that document-verified withholding has been recorded: `withholding_verified_cents` must not be null (`ERR_INVALID_REQUEST`, a resource-state precondition evaluated only once the transition's state legality has passed), and the return must still be in scope (`ERR_OUT_OF_SCOPE`). Each entry into `PENDING_QR` computes the binding `final_refund_cents`; before the first submission the field is null. Submission also releases the preparer's caseload: `active_case_count` decreases by one.

The final determination proceeds in a pinned order. First, tier selection on `qualifying_children`: with no qualifying children the credit rate is 10 percent and its cap is $600; with one qualifying child the rate is 20 percent and the cap is $4,000; with two or more the rate is 25 percent and the cap is $6,500. Second, the final earned-income credit is the lesser of the tier rate multiplied by `earned_income_cents` — the multiplication rounded half-up to whole cents — and the tier cap. Third, the tax liability is 12 percent of the sum of `wages_cents` and `other_income_cents`, rounded half-up to whole cents. Finally, `final_refund_cents` is the verified withholding plus the final credit minus the liability, floored at zero. Because the rate structure and the liability treatment differ from the provisional variant, identical inputs generally produce a different figure than the intake estimate.

Review itself is performed by a `QualityReviewer` and ends in one of two verdicts. Passing moves `PENDING_QR` to `QR_PASSED`; failing moves it to `QR_FAILED`. Both verdicts enforce the same two gates: the reviewer must be `ACTIVE` and hold `CURRENT` passed `INTAKE_QR` and `ADVANCED` certifications for season 2026 (`ERR_REVIEWER_NOT_CERTIFIED`), and the reviewer must not be the return's preparer — the segregation-of-duties rule (`ERR_REVIEWER_IS_PREPARER`). Failing additionally requires `review_notes` explaining the deficiency (`ERR_INVALID_REQUEST`). Either verdict records the acting reviewer as the return's `reviewer_id`; a failing verdict also increments `qr_failure_count`.

A failed review routes the return back to its owner: from `QR_FAILED` the owning preparer returns it to `IN_PREPARATION` with no further preconditions, and the preparer's `active_case_count` rises by one. The return may cycle through review repeatedly, each failed pass counted in `qr_failure_count`, until it passes or exits through referral or withdrawal (§3.8).

### 3.6. Split Refunds, the Savings Match, and Transmission

Taxpayers electing direct deposit may split their refund across up to three accounts. While the return is `INTAKE_STARTED`, `IN_PREPARATION`, or `QR_PASSED` — that is, right up until transmit — the owning `Preparer` may add a refund allocation supplying `tax_return_id`, an `account_type` of `CHECKING` or `SAVINGS`, a `routing_number` of exactly nine digits, a masked `account_number_mask` such as ****6789, and an `amount_cents` of at least one cent. A fourth allocation is rejected with `ERR_ALLOCATION_LIMIT`, and adding or removing an allocation against any other return status is rejected with `ERR_INVALID_TRANSITION`. Removing an allocation is permitted in the same window and returns no content. Allocations may be added and removed regardless of the return's `refund_method`; the direct-deposit conservation rule below bites only at transmission.

Each change to the allocation set — and any edit touching allocation-relevant state — recomputes the sponsor's savings-match incentive, `savings_match_cents`. For every allocation whose `account_type` is `SAVINGS`, the line's match is 50 percent of its `amount_cents`, floored down to whole dollars; the return's match is the sum of those per-line matches, capped at $100. The per-line flooring happens before summation, so two `SAVINGS` lines of 3,333 cents each contribute 1,600 cents apiece for a match of 3,200 cents — flooring the summed amount instead would wrongly yield 3,300 cents and is forbidden.

Transmission — `QR_PASSED` to `TRANSMITTED`, performed by the `SiteCoordinator` — e-files the return. The site must be `OPEN` (`ERR_SITE_NOT_OPEN`), and money conservation is enforced: when the return's `refund_method` is `DIRECT_DEPOSIT`, its allocations must number between one and three and their `amount_cents` must sum exactly to the return's `final_refund_cents`, failing which the transmission is rejected with `ERR_ALLOCATION_SUM_MISMATCH`; a `PAPER_CHECK` return faces no allocation gate. Each successful transmission increments `submission_count` by one and stamps `transmitted_at` with the current logical time.

### 3.7. Acknowledgement, Rejection Follow-Up, and Rework

Once transmitted, the return awaits the IRS acknowledgement, which the `SiteCoordinator` records. Acceptance — `TRANSMITTED` to `ACCEPTED` — records `first_ack_outcome` as `ACCEPTED` if this is the return's first acknowledgement; the field stays null until then and is never rewritten afterwards. Acceptance also triggers a financial-capability nudge: if the return has at least one refund allocation whose `account_type` is `SAVINGS` and no financial-service referral of type `SAVINGS_ACCOUNT` exists for the return yet, the system automatically creates one in `OFFERED` status with `source` `AUTO_ON_ACCEPT` and a null `offered_by`.

Rejection — `TRANSMITTED` to `REJECTED` — requires the coordinator to supply the IRS `rejection_code` and `rejection_text` (`ERR_INVALID_REQUEST` if either is missing). The return's `first_ack_outcome` is recorded as `REJECTED` if this is the first acknowledgement, and an e-file rejection record is created, bound to the return through `tax_return_id`, snapshotting `submission_number` equal to the return's current `submission_count`, and opening follow-up work in `OPEN` status.

Follow-up on a rejection is a taxpayer-contact duty shared by the `QualityReviewer` and the `SiteCoordinator`. Each rejection's `follow_up_due_at` is its creation time plus five days, and its `follow_up_overdue` flag is true whenever its `follow_up_status` is not yet `RESOLVED` and the current logical time has passed the due instant. Recording a follow-up takes an `outcome`: recording `CONTACTED` from `OPEN` stamps `contacted_at` with the current logical time, and recording `RESOLVED` — from `OPEN` or from `CONTACTED` — requires a `resolution_note` (`ERR_INVALID_REQUEST` when absent) and stamps `resolved_at`. `RESOLVED` is terminal for the rejection.

A rejected return can be reworked: from `REJECTED` back to `IN_PREPARATION`, by the owning preparer (`ERR_NOT_RETURN_OWNER`). Rework is barred while any of the return's e-file rejections has a `follow_up_status` other than `RESOLVED` (`ERR_REJECTION_UNRESOLVED`), and it is barred once the return's `submission_count` has reached three (`ERR_MAX_SUBMISSIONS_REACHED`) — a return that has exhausted three submissions must be referred out instead (§3.8). Successful rework raises the preparer's `active_case_count` by one; the return may then be edited again, resubmitted to review — which recomputes the final refund on re-entry into `PENDING_QR` — and transmitted once more.

Closing the season's bookkeeping on an accepted return — `ACCEPTED` to `COMPLETED`, by the `SiteCoordinator` — requires confirmation that the refund was disbursed and the taxpayer told: both `disbursement_confirmed` and `taxpayer_notified` must be true (`ERR_INVALID_REQUEST`). `COMPLETED` is terminal.

### 3.8. Referrals Out of Scope, Withdrawal, and Financial Capability Services

Referral is the dignified exit for work the program cannot do. From any of `INTAKE_STARTED`, `IN_PREPARATION`, `PENDING_QR`, `QR_FAILED`, `QR_PASSED`, or `REJECTED`, a `Preparer`, a `QualityReviewer`, or the `SiteCoordinator` may move the return to `REFERRED`, supplying a `referral_reason` and a `referral_destination` (`ERR_INVALID_REQUEST` when either is absent); both are recorded on the return. Referral out of `IN_PREPARATION` releases the preparer's caseload, decreasing `active_case_count` by one. For a return whose `out_of_scope` is true, referral or withdrawal are the only exits: any attempt to advance it toward preparation or review is rejected with `ERR_OUT_OF_SCOPE`.

Withdrawal covers every other abandonment. From the same six non-terminal states, a `Preparer` or the `SiteCoordinator` may move the return to `WITHDRAWN`, supplying a `withdrawal_reason` (`ERR_INVALID_REQUEST` when absent on an actor-driven withdrawal). Cascade-driven withdrawals need no client-supplied reason because the cascade supplies its own: `APPOINTMENT_CANCELLED`, `SITE_SUSPENDED`, or `VOLUNTEER_INACTIVATED` (§3.1 through §3.3). Withdrawal from `IN_PREPARATION` likewise decreases the preparer's `active_case_count` by one. `COMPLETED`, `REFERRED`, and `WITHDRAWN` are the return's terminal states.

One invariant protects the financial-capability pipeline: every transition of a return into `WITHDRAWN` or `REFERRED` — whether actor-driven or cascade-driven — voids the return's financial-service referrals still in `OFFERED` or `ACCEPTED`, moving them to `VOID`. Referrals already `ENROLLED` or `DECLINED` are history and remain untouched.

The financial-capability program itself is simple. On any return that has not reached a terminal state, a `Preparer` or the `SiteCoordinator` may offer an add-on service by naming a `service_type` — one of `SAVINGS_ACCOUNT`, `CREDIT_COUNSELING`, `BANK_ACCOUNT`, or `FINANCIAL_COACHING`. Offering against a return already `COMPLETED`, `REFERRED`, or `WITHDRAWN` is rejected with `ERR_INVALID_TRANSITION`, since terminal returns accept no further activity. A manually offered referral begins in `OFFERED` with `offered_by` set to the actor's volunteer id and `source` `MANUAL`; the auto-created rows of §3.7 instead carry `source` `AUTO_ON_ACCEPT` and a null `offered_by`. From `OFFERED`, the taxpayer may accept — moving the referral to `ACCEPTED` — and then enroll, moving it to `ENROLLED`; or the taxpayer may decline, moving it from `OFFERED` to `DECLINED`. `ENROLLED`, `DECLINED`, and `VOID` are the referral's terminal states; `VOID` is reachable only through the voiding invariant above, and any client attempt to drive a referral to `VOID` — or any transition other than the three listed — is rejected with `ERR_INVALID_TRANSITION`.

### 3.9. Season Statistics and Sponsor Reporting

A `SiteCoordinator` generates a statistics report for its site by supplying a `period_start` and a `period_end`; the period end must be strictly after the period start (`ERR_REPORT_PERIOD_INVALID`). The site's current status places no constraint on report generation. The period values are labels only: every aggregate is computed lifetime-to-date at generation time, the snapshot is computed once and frozen immutably, `generated_at` is stamped with the current logical time, the report's `site_id` is taken from the site addressed by the request, and the new report begins in `DRAFT`.

The snapshot counts every return of the site, whatever its status. `returns_prepared_count` counts returns whose `reached_preparation` is true; `returns_transmitted_count` counts returns with a `submission_count` of at least one; `returns_accepted_count` counts returns in `ACCEPTED` or `COMPLETED`; `returns_rejected_open_count` counts returns currently `REJECTED`; `returns_referred_count` and `returns_withdrawn_count` count returns in those terminal states; `qr_rework_total` sums the `qr_failure_count` across the site's returns; and `first_pass_accepted_count` counts returns whose `first_ack_outcome` is `ACCEPTED`. The financial-capability footprint appears as `financial_referrals_accepted_count` — referrals of the site's returns in `ACCEPTED` or `ENROLLED` — and `savings_match_total_cents` — the sum of `savings_match_cents` over the site's returns in `TRANSMITTED`, `ACCEPTED`, or `COMPLETED`.

Two acceptance rates, reported in basis points as integers rounded half-up, measure e-file quality from different angles; both are null when no return of the site has ever been transmitted. `first_pass_acceptance_rate_bp` is the first-pass accepted count multiplied by ten thousand and divided by the transmitted count: its numerator credits only returns whose first acknowledgement was an acceptance, so a return rejected on first acknowledgement and later accepted contributes nothing here. `final_resolution_rate_bp` divides the accepted-or-completed count by the same denominator, crediting eventual success regardless of first-pass history — so for the same data the final-resolution rate is always at least the first-pass rate, and strictly higher whenever any transmitted return was rejected before ultimately being accepted.

The report workflow is short and segregated: the `SiteCoordinator` submits a `DRAFT` report — permitted only to a coordinator-flagged volunteer of the report's own site, per the binding of §2.1 — moving it to `SUBMITTED`, and a `SponsorAdmin` acknowledges a `SUBMITTED` report, moving it to `ACKNOWLEDGED`, which is terminal. Both roles may list a site's reports.

## 4. Endpoint Definitions

Operations that create a new resource — a site, a volunteer, a certification attempt, a taxpayer, an appointment, a tax return, a refund allocation, a site report, or a financial-service referral — return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, record a follow-up or identity verification, set the logical clock, or simply read resources return a `200 OK` status code. Removing a refund allocation returns `204 No Content` with an empty body. The narratives of §3 define each operation's request fields, preconditions, and side effects; this table is the address book.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock | SponsorAdmin |
| POST   | `/sites` | Create a VITA site | SponsorAdmin |
| GET    | `/sites/{id}` | Get a site | Any |
| POST   | `/sites/{id}/state` | Transition site status per the Site state machine | SiteCoordinator |
| GET    | `/sites/{id}/volunteers` | List volunteers of a site | Any |
| POST   | `/sites/{id}/reports` | Generate a season statistics report snapshot | SiteCoordinator |
| GET    | `/sites/{id}/reports` | List reports of a site | SiteCoordinator, SponsorAdmin |
| POST   | `/site-reports/{id}/state` | Submit or acknowledge a report | SiteCoordinator, SponsorAdmin |
| POST   | `/volunteers` | Register a volunteer at a site | SiteCoordinator, SponsorAdmin |
| GET    | `/volunteers/{id}` | Get a volunteer | Any |
| POST   | `/volunteers/{id}/state` | Activate or inactivate a volunteer | SiteCoordinator, SponsorAdmin |
| POST   | `/volunteers/{id}/certifications` | Record a certification test attempt | SiteCoordinator, SponsorAdmin |
| GET    | `/volunteers/{id}/certifications` | List certification attempts of a volunteer | Any |
| POST   | `/taxpayers` | Register a taxpayer | Screener, SiteCoordinator |
| GET    | `/taxpayers/{id}` | Get a taxpayer | Any |
| POST   | `/taxpayers/{id}/verify-identity` | Record photo-ID verification | Screener, SiteCoordinator |
| POST   | `/appointments` | Schedule an appointment | Screener, SiteCoordinator |
| GET    | `/appointments` | List appointments with optional filters | Any |
| GET    | `/appointments/{id}` | Get an appointment | Any |
| PATCH  | `/appointments/{id}` | Reschedule or reassign a scheduled appointment | Screener, SiteCoordinator |
| POST   | `/appointments/{id}/state` | Transition an appointment | Screener, SiteCoordinator |
| POST   | `/tax-returns` | Open a return from a checked-in appointment | Preparer |
| GET    | `/tax-returns` | List returns with optional filters | Any |
| GET    | `/tax-returns/{id}` | Get a return | Any |
| PATCH  | `/tax-returns/{id}` | Edit intake and preparation fields of a return | Screener, Preparer, SiteCoordinator |
| POST   | `/tax-returns/{id}/state` | Drive the return lifecycle | Preparer, QualityReviewer, SiteCoordinator |
| POST   | `/refund-allocations` | Add a direct-deposit allocation to a return | Preparer |
| DELETE | `/refund-allocations/{id}` | Remove an allocation | Preparer |
| GET    | `/tax-returns/{id}/refund-allocations` | List allocations of a return | Any |
| GET    | `/tax-returns/{id}/rejections` | List e-file rejections of a return | Any |
| POST   | `/efile-rejections/{id}/follow-up` | Record taxpayer follow-up on a rejection | QualityReviewer, SiteCoordinator |
| POST   | `/tax-returns/{id}/financial-referrals` | Offer a financial-capability service | Preparer, SiteCoordinator |
| GET    | `/tax-returns/{id}/financial-referrals` | List financial-service referrals of a return | Any |
| POST   | `/financial-referrals/{id}/state` | Advance a referral | Preparer, SiteCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue is the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RETURN_OWNER` | 403 Forbidden |
| `ERR_VOLUNTEER_NOT_CERTIFIED` | 403 Forbidden |
| `ERR_REVIEWER_NOT_CERTIFIED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TAXPAYER_DUPLICATE_SSN` | 409 Conflict |
| `ERR_OPEN_RETURN_EXISTS` | 409 Conflict |
| `ERR_APPOINTMENT_ALREADY_USED` | 409 Conflict |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_ACTIVE` | 409 Conflict |
| `ERR_SITE_NOT_OPEN` | 409 Conflict |
| `ERR_SITE_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_APPOINTMENT_OVERLAP_VOLUNTEER` | 409 Conflict |
| `ERR_SITE_CAPACITY_FULL` | 409 Conflict |
| `ERR_REJECTION_UNRESOLVED` | 409 Conflict |
| `ERR_MAX_SUBMISSIONS_REACHED` | 409 Conflict |
| `ERR_IDENTITY_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_REVIEWER_IS_PREPARER` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SITE_WINDOW` | 422 Unprocessable Entity |
| `ERR_DOCUMENTS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_LIMIT` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_SUM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_INVALID` | 422 Unprocessable Entity |
