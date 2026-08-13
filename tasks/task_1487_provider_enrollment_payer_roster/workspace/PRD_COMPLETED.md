# Provider Enrollment & Payer Roster Synchronization API — Product Requirements Document

## 1. Introduction

A medical practice group cannot bill a payer for a clinician's services until that clinician is enrolled with that payer, and the enrollment must remain continuously valid: CAQH profiles must be re-attested on a fixed cycle, Medicare and commercial payers demand periodic revalidation, and a lapsed or terminated enrollment converts revenue into denials or, worse, into money that must be clawed back. Large groups increasingly shortcut the per-application channel through delegated credentialing, submitting whole rosters that the payer confirms line by line — a channel that introduces its own risks around stale submissions, duplicated enrollments, and unreviewed sign-offs.

This document specifies an API that runs both enrollment channels as one system of record. It governs practice-group and clinician onboarding, payer configuration, the CAQH attestation cycle, the enrollment application lifecycle, delegated credentialing agreements and roster adjudication, claims intake gating, revalidation and deactivation, and terminations with retro-effective recoupment. A server-owned logical clock — never the wall clock — drives every time-based compliance transition deterministically, and all multi-entity effects are applied immediately, within the request or clock sweep that triggers them, so that balances, statuses, and roster rollups are never eventually-consistent.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. All endpoints are mounted under `/api`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `ComplianceOfficer`, `EnrollmentSpecialist`, `PayerRepresentative`, and `Provider`. A request missing either header — an empty header value counts as missing — or carrying a role name that is not one of these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). All retrieval endpoints are shared: every declared role may call any GET operation in the API.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `ComplianceOfficer`, `EnrollmentSpecialist`, or `PayerRepresentative`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `submitted_by_user_id` on a roster file — but it does not compare it to any entity's `id`. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting Provider, and ownership checks on any resource that references a Provider compare the resource's foreign-key field to `X-User-ID`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`, the prefix followed by twenty-four lowercase hexadecimal characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.5) rather than the wall clock.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses follow this standard envelope format:

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
- The `message` provides a human-readable explanation of what went wrong. The same envelope also answers a request that matches no defined route — including an unsupported method on a defined path — with `ERR_NOT_FOUND` (HTTP 404), and an unexpected server fault with `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination and List Filtering

List endpoints paginate through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless a collection states otherwise, list results are sorted by creation timestamp in ascending order; the one exception is the line listing of a roster file, which is ordered by `line_index` ascending so that the payer sees lines in submission order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. A `limit` or `offset` that does not parse as an integer is ignored in favor of its default rather than rejected, and out-of-range values are clamped — `limit` into [1, 100], `offset` up to 0 — so no pagination parameter ever produces an error. `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Ties on creation timestamp are broken by insertion order, earlier-created first.

Collections support equality filters drawn from their foreign keys and statuses; when several filter parameters are supplied on one request they combine conjunctively — an item is returned only if it matches every supplied filter. Enrollment applications filter by `provider_id`, `payer_id`, and `status`; enrollment records by `provider_id`, `payer_id`, `source_application_id`, `source_roster_line_id`, and `status`; delegation agreements by `payer_id`, `practice_group_id`, and `status`; roster files by `agreement_id` and `status`; a roster file's lines by `status`; claims by `provider_id`, `payer_id`, and `status`; and a practice group's providers by `status`.

### 2.4. Common Resource Properties

All ten resources — PracticeGroup, Provider, Payer, CAQHProfile, EnrollmentApplication, EnrollmentRecord, DelegatedCredentialingAgreement, RosterFile, RosterLine, and Claim — share one system-managed property set. Each carries an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp recording when the resource was created; an `updated_at` timestamp refreshed on every change to the resource; and a `version` integer that starts at 1 on creation and increments by one on every mutation. Both timestamps are ISO 8601 UTC values with three fractional digits. Mutations include client-driven writes and system-driven ones alike: a status flipped by a clock sweep, a recomputed rollup count, or a cascade-applied denial each refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. The Logical Clock

The server keeps a logical clock that is deliberately decoupled from the wall clock, so that time-driven compliance behavior is deterministic and testable. At startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `ComplianceOfficer`-only clock-control capability advances it: the caller supplies a `to_iso8601` instant and the response reports the resulting `current_utc`. The clock is monotonic non-decreasing; an attempt to set it to an instant earlier than its current value is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). A `to_iso8601` value that does not parse as an ISO 8601 timestamp fails schema validation with `ERR_INVALID_REQUEST` (HTTP 400), and one without an explicit offset is read as UTC. Setting the clock to exactly its current value is permitted and fires the sweep like any other set.

Every advance of the logical clock fires a sweep that re-evaluates three families of time-based state: CAQH profiles move between their current and warning states, enrollment records enter their revalidation windows or deactivate past their due dates, and delegation agreements expire. Every timestamp the system records on a resource — `submitted_at`, `approved_at`, `last_attested_at`, `last_revalidation_completed_at` — is taken from this logical clock, never from wall-clock time.

### 2.6. Date, Timestamp, and Monetary Precision

Calendar dates (effective dates, termination dates, service dates, due dates) are represented as strict `YYYY-MM-DD` strings — a four-digit year and zero-padded two-digit month and day naming a valid Gregorian calendar date — and compared at day precision. Timestamps are ISO 8601 UTC values with three fractional digits; clock-sweep comparisons against timestamp-valued deadlines are made at second precision. Where a due date is snapped to the end of a calendar month, the snap uses the Gregorian calendar. All money is carried as integer cents — there are no fractional-cent amounts anywhere in the system. The one derived monetary value, the per-claim recoupment fee, is computed to zero decimal places using round-half-up, per claim, as detailed in §3.8.

### 2.7. Enrollment Intervals and Overlap Semantics

Two interval disciplines coexist, and confusing them is the classic integration bug in this domain. Enrollment records occupy **half-open** intervals: a record covers service dates from its `effective_date` up to but not including its `termination_date`. Two records for the same provider and payer may never overlap, but touching is allowed — a new record whose effective date equals a prior terminated record's termination date is a legal back-to-back enrollment. As a consequence, at most one enrollment record per provider–payer pair can be in `ACTIVE` or `PENDING_REVALIDATION` at any moment.

Delegated credentialing agreements, by contrast, occupy **closed** intervals from `effective_date` through `expiry_date`, both endpoints inclusive. Two agreements for the same practice group and payer whose status is anything other than `TERMINATED` may not intersect at all; sharing even a single boundary date already counts as overlap and is rejected.

### 2.8. Validation Order and Error Precedence

When several checks could fail on the same request, the server evaluates them in a fixed order and reports the first failure. The tiers, from first to last, are:

1. **Header context** — both headers present and the role name declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization** — the role is permitted on the endpoint, else `ERR_FORBIDDEN_FOR_ROLE` (403).
3. **Existence** — path identifiers resolve to existing resources, validated left to right (a parent before the child beneath it), and body foreign keys such as `provider_id`, `payer_id`, and `agreement_id` resolve, else `ERR_NOT_FOUND` (404).
4. **Request schema** — required fields present, enum members valid, date fields parse as `YYYY-MM-DD`, integer fields are integers, a claim's `amount_cents` is positive, and an agreement's `expiry_date` is strictly later than its `effective_date`, else `ERR_INVALID_REQUEST` (400). A missing, malformed, or non-object JSON body is treated as an empty object, so its failures surface here as missing-required-field errors.
5. **Actor scope** — a provider attests only their own CAQH profile, and a roster's submitter never reconciles it, else `ERR_PROFILE_OWNERSHIP_MISMATCH` or `ERR_SEGREGATION_OF_DUTIES` (403).
6. **Optimistic concurrency** — the roster submission's expected agreement version matches, else `ERR_STALE_AGREEMENT_VERSION` (412).
7. **State guards** — the target resource's state permits the transition, else `ERR_INVALID_STATE_TRANSITION`, `ERR_ROSTER_LINE_NOT_PENDING`, `ERR_CLAIM_NOT_RECOUPED`, or `ERR_REVALIDATION_NOT_DUE` (409). Within this tier the most specific resource's error wins: a line-level violation such as `ERR_ROSTER_LINE_NOT_PENDING` is reported before the parent file's state violation `ERR_INVALID_STATE_TRANSITION`.
8. **Compliance gates** — the provider is not terminated, the CAQH attestation is current, and the agreement is active where required, else `ERR_PROVIDER_TERMINATED`, `ERR_CAQH_ATTESTATION_NOT_CURRENT`, or `ERR_AGREEMENT_NOT_ACTIVE` (409).
9. **Referential business rules** — roster-line providers belong to the agreement's practice group and TERM lines target an existing enrollment, else `ERR_PROVIDER_GROUP_MISMATCH` or `ERR_NO_ACTIVE_ENROLLMENT` (422).
10. **Temporal rules** — retroactive windows, termination-date floors, and future service dates, else `ERR_RETRO_WINDOW_EXCEEDED`, `ERR_TERMINATION_DATE_INVALID`, or `ERR_FUTURE_SERVICE_DATE` (422).
11. **Uniqueness and overlap** — duplicate NPIs, in-flight applications, enrollment and agreement overlap, empty rosters, and clock regression, else `ERR_DUPLICATE_NPI`, `ERR_APPLICATION_IN_FLIGHT`, `ERR_ENROLLMENT_OVERLAP`, `ERR_AGREEMENT_OVERLAP` (409), `ERR_EMPTY_ROSTER`, or `ERR_CLOCK_REGRESSION` (422).

### 2.9. Optimistic Concurrency Control on Roster Submission

Exactly one endpoint in the API is guarded by optimistic concurrency control: roster submission. A submission must carry `expected_agreement_version`, the `version` of the delegation agreement as the client last observed it. If the agreement's current `version` differs, the submission is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), because the client is acting on an agreement state it has not observed. This is not a theoretical concern: every successful roster submission increments the agreement's `version` by one, so a second submission built on a stale read of the agreement fails with this error instead of silently superseding a roster the caller never saw. No endpoint other than roster submission accepts a version field.

### 2.10. Resolving Nested Paths and Referenced Resources

Requests that address a resource nested beneath another validate path identifiers sequentially from left to right, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND`. A line-level roster action, for example, addresses the file's `id` and then the line's `lineId`; the file is resolved before the line is even looked for, so a request naming a nonexistent file fails on the file regardless of whether the line exists. The same left-to-right discipline applies to a provider created through a practice group's collection: the group is resolved before the request body is considered. Foreign keys supplied in request bodies — `provider_id`, `payer_id`, `agreement_id`, and on agreement creation `practice_group_id` — must likewise resolve to existing resources, or the request fails with `ERR_NOT_FOUND`. This existence check applies when the supplied value is a string; a foreign key that is absent or not a string is instead left to schema validation and fails there with `ERR_INVALID_REQUEST`.

### 2.11. Rollups, Cascades, and Immediate Consistency

A roster file does not hold an independently set status; its headline numbers and most of its status transitions are derived from the states of its lines, recomputed after every line mutation. Conversely, events at the provider or enrollment-record level cascade downward without delay: a termination reaches from the provider through its enrollment records to individual claims and finally to the provider's outstanding recoupment balance, all within the triggering request. The system applies every such effect immediately — there is no background settlement, no eventual-consistency window in which a claim's status and a record's status could disagree about whether the record covered the claim.

## 3. Business Logic & Workflows

### 3.1. Practice Groups, Clinician Onboarding, and Payer Configuration

A `ComplianceOfficer` opens the hierarchy by registering a practice group with its legal `name`, federal `tax_id`, and type-2 `group_npi`. An `EnrollmentSpecialist` then onboards clinicians into the group by creating providers through the group's provider collection; the provider's owning group is taken from the creation path and recorded as `practice_group_id`. Each provider carries a type-1 `npi`, a `full_name`, and a `specialty`. The `npi` must be unique across every provider in the system: a duplicate is rejected with `ERR_DUPLICATE_NPI`. A new provider starts in `ACTIVE` status with `termination_date` and `termination_reason` both null and a `recoupment_balance_cents` of zero. Creating a provider automatically creates exactly one CAQH profile for them, in `NEVER_ATTESTED` status with `last_attested_at` and `due_at` both null; reading a provider's CAQH profile returns an array containing that single profile. A group's providers can be listed through the group's collection, optionally filtered by `status`, and the roster lines that reference a given provider can likewise be listed from the provider.

Payer configuration is a `ComplianceOfficer` responsibility. Each payer is registered with a `payer_code`, a display `name`, an `is_medicare` flag, an `effective_date_policy` of `APPROVAL_DATE` or `RETRO_90`, a `claims_hold_enabled` switch, and a `revalidation_interval_days`. These six choices steer downstream behavior throughout the document: the Medicare flag snaps revalidation due dates to month-end (§3.7), the effective-date policy selects between the two enrollment-dating variants (§3.3), the claims-hold switch decides whether uncovered claims wait or die at intake (§3.6), and the interval sets the revalidation cadence — a Medicare payer is conventionally configured with an interval of 1825 days, that is, five years.

### 3.2. The CAQH Attestation Cycle

CAQH attestation is the provider's own act, and the system enforces that literally: when `X-User-Role` is `Provider`, the caller may attest only the profile whose `provider_id` equals their `X-User-ID`. Any other pairing is rejected with `ERR_PROFILE_OWNERSHIP_MISMATCH` (HTTP 403).

Attestation is permitted from every profile status — `NEVER_ATTESTED`, `ATTESTED`, `DUE`, and `LAPSED` alike — and always lands in `ATTESTED`. Each attestation stamps `last_attested_at` with the current logical clock and recomputes `due_at` as exactly 120 days later, so a re-attestation restarts the cycle from scratch, whether it happens inside the warning window, after a lapse, or long before either. The cycle is unbounded: `ATTESTED` gives way to `DUE`, `DUE` to `LAPSED`, and a fresh attestation returns the profile to `ATTESTED` again.

The warning and lapse transitions belong to the clock sweep. A profile in `ATTESTED` enters `DUE` once the logical clock reaches the instant thirty days before `due_at`, and it remains `DUE` through `due_at` itself. Only when the logical clock is strictly later than `due_at` does the profile become `LAPSED`; at the exact instant of `due_at` the profile is `DUE`, never `LAPSED`. The same strict-greater rule moves a `DUE` profile to `LAPSED`. The sweep touches only profiles currently in `ATTESTED` or `DUE`: a `NEVER_ATTESTED` profile is never swept, and a freshly attested profile outside the warning window is left alone.

Attestation status is a gate on the application channel. Submitting, resubmitting, or approving an enrollment application requires the provider's profile to be `ATTESTED` or `DUE`; a profile that is `NEVER_ATTESTED` or `LAPSED` blocks all three with `ERR_CAQH_ATTESTATION_NOT_CURRENT` (§3.3).

### 3.3. The Enrollment Application Path

The per-application channel begins when an `EnrollmentSpecialist` drafts an application naming the `provider_id`, the `payer_id`, an `enrollment_scope` of `GROUP_LINK` or `INDIVIDUAL`, and a `requested_effective_date`. The draft is born in `DRAFT` with `submitted_at`, `approved_at`, `info_request_reason`, and `decision_reason` all null. Creation itself is guarded: the requested date may be no earlier than ninety days before the current logical date, or the request fails with `ERR_RETRO_WINDOW_EXCEEDED`; at most one application per provider–payer pair may be in flight — that is, in `DRAFT`, `SUBMITTED`, or `PENDING_INFO` — or creation fails with `ERR_APPLICATION_IN_FLIGHT`; and if an enrollment record for the pair is already `ACTIVE` or `PENDING_REVALIDATION`, creation fails with `ERR_ENROLLMENT_OVERLAP` rather than allowing a doomed draft.

Submitting moves the application `DRAFT → SUBMITTED` and stamps `submitted_at` from the logical clock. Two compliance gates guard the transition: the provider must still be `ACTIVE` (else `ERR_PROVIDER_TERMINATED`) and the provider's CAQH profile must be `ATTESTED` or `DUE` (else `ERR_CAQH_ATTESTATION_NOT_CURRENT`). From `SUBMITTED`, a `PayerRepresentative` may push the application into `PENDING_INFO` with a request for more information, supplying a `reason` that is recorded as `info_request_reason`. The specialist answers by resubmitting, which returns the application `PENDING_INFO → SUBMITTED` under the same two compliance gates and refreshes `submitted_at`; this information-request loop may repeat any number of times.

Approval is the pivotal transition. A `PayerRepresentative` approving a `SUBMITTED` application re-checks both compliance gates at approval time — a provider terminated mid-adjudication yields `ERR_PROVIDER_TERMINATED`, and a CAQH profile that has since lapsed yields `ERR_CAQH_ATTESTATION_NOT_CURRENT` — and then enforces enrollment exclusivity: no record for the pair may be `ACTIVE` or `PENDING_REVALIDATION`, and the computed effective date must not fall inside any `TERMINATED` record's half-open interval for the pair, although an effective date exactly equal to a prior record's termination date is permitted; either violation is `ERR_ENROLLMENT_OVERLAP`. Approval stamps `approved_at`, moves the application to `APPROVED`, and creates the enrollment record.

The record's `effective_date` depends on the payer's `effective_date_policy`. Under `APPROVAL_DATE`, the effective date is simply the calendar day of approval; the `requested_effective_date` is ignored entirely. Under `RETRO_90`, the effective date is the later of the requested effective date and the day ninety days before the approval day — so identical inputs yield an earlier effective date than the approval-date variant whenever the requested date precedes the approval day. The new record starts `ACTIVE`, records the application as its `source_application_id`, copies the application's `enrollment_scope`, and sets `benefit_assignment` to `GROUP` when the scope is `GROUP_LINK` (benefits reassigned to the practice group) and to `INDIVIDUAL` otherwise. Its `last_revalidation_completed_at` is the approval instant, and `revalidation_due_date` and `revalidation_window_start` are computed per the schedule in §3.7. Activation also releases eligible held claims for the provider–payer pair, per §3.6.

The two remaining exits are simple. A `PayerRepresentative` may reject a `SUBMITTED` application with a `reason`, recorded as `decision_reason`, moving it to `REJECTED`. An `EnrollmentSpecialist` may withdraw an application from `DRAFT`, `SUBMITTED`, or `PENDING_INFO`, moving it to `WITHDRAWN`. `APPROVED`, `REJECTED`, and `WITHDRAWN` are terminal; invoking any further transition on a terminal application is `ERR_INVALID_STATE_TRANSITION`. Provider termination also withdraws in-flight applications system-side (§3.8).

### 3.4. Delegated Credentialing Agreements and Roster Submission

Delegated credentialing lets a group roster its clinicians to a payer in bulk, but only under a live agreement. A `ComplianceOfficer` creates the agreement with `practice_group_id`, `payer_id`, an `effective_date`, and an `expiry_date`; the expiry must be strictly later than the effective date or the request fails schema validation with `ERR_INVALID_REQUEST`. Overlap is checked per §2.7: a new agreement whose closed interval intersects any non-`TERMINATED` agreement for the same group and payer — even at one shared boundary date — is rejected with `ERR_AGREEMENT_OVERLAP`. An agreement starts `ACTIVE`, becomes `EXPIRED` via the clock sweep once the current logical date passes `expiry_date`, and may be terminated early by a `ComplianceOfficer`, moving `ACTIVE → TERMINATED`; neither expiry nor termination cascades into roster files or enrollment records.

With an agreement in force, an `EnrollmentSpecialist` submits a roster file carrying the `agreement_id`, the OCC field `expected_agreement_version` (§2.9), and a non-empty `lines` array — an empty array is rejected with `ERR_EMPTY_ROSTER`. The agreement must be `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`. Each line names a `provider_id`, an `action` of `ADD` or `TERM`, and an `expected_effective_date` — the expected enrollment date for an addition, the expected termination date for a removal — which may be no earlier than ninety days before the current logical date, else `ERR_RETRO_WINDOW_EXCEEDED`. `ADD` lines additionally carry `enrollment_scope` and `benefit_assignment`; those two fields are meaningless on a removal — any values supplied for them on a `TERM` line are ignored, and the stored line carries null for both. Every line's provider must belong to the agreement's practice group, or submission fails with `ERR_PROVIDER_GROUP_MISMATCH`.

A submitted file is born in `SUBMITTED` with every line `PENDING`, each line's `line_index` assigned zero-based in request order and its containing file recorded as `roster_file_id`. The file records the submitter's opaque identifier as `submitted_by_user_id` — the value the segregation-of-duties check will later compare against — and stamps `submitted_at` from the logical clock. Submission increments the agreement's `version` by one, and it supersedes the prior `SUBMITTED` file for the same agreement: that file moves to `SUPERSEDED`, its still-`PENDING` lines move to `SUPERSEDED` with it, and its rollup counts are recomputed.

### 3.5. Roster Line Adjudication, Rollup, and Reconciliation

Adjudication is the payer's turn. A `PayerRepresentative` confirms a line by supplying the `confirmed_effective_date` the payer actually granted, or rejects it with a `reason` recorded as `rejection_reason`. Both actions require the line to be `PENDING` — confirming or rejecting any other line state fails with `ERR_ROSTER_LINE_NOT_PENDING` — and require the containing file to be `SUBMITTED`, else `ERR_INVALID_STATE_TRANSITION`; when both are violated, the line-level error is the one reported (§2.8).

Confirmation splits on date equality. When the confirmed date equals the line's `expected_effective_date`, the line becomes `CONFIRMED` and its enrollment effects apply immediately. For an `ADD` line, the confirm-time exclusivity check mirrors the application path: no record for the provider and the agreement's payer may be `ACTIVE` or `PENDING_REVALIDATION`, and the confirmed date must not fall inside a `TERMINATED` record's half-open interval — equality with a prior termination date permitted — else `ERR_ENROLLMENT_OVERLAP`. The created record starts `ACTIVE`, points back to the line via `source_roster_line_id`, takes the confirmed date as its `effective_date`, copies the line's `enrollment_scope` and `benefit_assignment`, stamps `last_revalidation_completed_at` from the logical clock, computes its revalidation schedule per §3.7, and then runs the claim-release cascade of §3.6. For a `TERM` line, an enrollment record for the pair in `ACTIVE` or `PENDING_REVALIDATION` must exist, else `ERR_NO_ACTIVE_ENROLLMENT`; confirmation terminates that record with `termination_date` equal to the confirmed date, firing the full record-termination cascade of §3.8. When the confirmed date differs from the expected date, the line instead becomes `DISCREPANCY`, the `confirmed_effective_date` is recorded, and no enrollment effect of any kind is applied yet.

A `DISCREPANCY` line is resolved by an `EnrollmentSpecialist` through the `accept_confirmed` decision. Accepting applies the deferred confirmation effects at the recorded `confirmed_effective_date` — record creation plus claim release for an addition, record termination plus the retro cascade for a removal — subject to the same `ERR_ENROLLMENT_OVERLAP` and `ERR_NO_ACTIVE_ENROLLMENT` guards as a clean confirm, and the line becomes `CONFIRMED`. Declining moves the line to `REJECTED` with `rejection_reason` set to the fixed string `DISCREPANCY_DECLINED`. Resolving a line that is not in `DISCREPANCY` fails with `ERR_ROSTER_LINE_NOT_PENDING`; unlike confirmation and rejection, resolution gates only on the line's state and does not re-check the containing file's status. `CONFIRMED`, `REJECTED`, and `SUPERSEDED` are terminal line states.

The file's headline is arithmetic over its lines. `total_lines` counts all lines; `pending_count`, `confirmed_count`, `rejected_count`, `discrepancy_count`, and `superseded_count` count the lines in each corresponding state, and the five status counts always sum to `total_lines`. While the file is `SUBMITTED`, its status is derived after every line mutation: any line still `PENDING` keeps the file `SUBMITTED`; with zero pending and every line `CONFIRMED` (and at least one line, which is guaranteed since empty rosters never exist), the file becomes `CONFIRMED`; otherwise — zero pending but some line rejected, superseded, or in discrepancy — it becomes `PARTIALLY_CONFIRMED`.

Final sign-off is segregation-of-duties territory. A `ComplianceOfficer` reconciles a file that has reached `CONFIRMED` or `PARTIALLY_CONFIRMED`, moving it to `RECONCILED` — but never the file they submitted themselves: if the reconciler's `X-User-ID` equals the file's `submitted_by_user_id`, the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Reconcile from any other file state is `ERR_INVALID_STATE_TRANSITION`. `RECONCILED` and `SUPERSEDED` are the file's terminal states.

### 3.6. Claims Intake and the Coverage Test

An `EnrollmentSpecialist` enters each claim with `provider_id`, `payer_id`, `service_date`, and `amount_cents`. The amount must be a positive integer number of cents and the service date must not be later than the current logical date, else `ERR_FUTURE_SERVICE_DATE`; a claim for a `TERMINATED` provider is refused outright with `ERR_PROVIDER_TERMINATED`. A new claim's `recoupment_fee_cents` is zero.

The claim's initial status is computed, never supplied. The coverage test asks whether an enrollment record exists for the claim's provider–payer pair whose status is `ACTIVE` or `PENDING_REVALIDATION`, whose `effective_date` is on or before the `service_date`, and which is either unterminated or has a `termination_date` strictly later than the `service_date`; the half-open overlap invariant of §2.7 guarantees at most one such record. A covered claim is born `RELEASED`. An uncovered claim born under a payer whose `claims_hold_enabled` is true becomes `HELD`, parked in anticipation of a future enrollment. An uncovered claim under a payer with holds disabled is born `DENIED` with `denial_reason` set to `PAYER_HOLD_DISABLED`.

The release cascade is how parked claims get paid. When an enrollment record becomes `ACTIVE` with effective date E — through application approval or roster ADD confirmation — every `HELD` claim of that provider–payer pair whose `service_date` is on or after E transitions `HELD → RELEASED`, processed in service-date order with ties broken by creation order; `HELD` claims dated before E stay `HELD`. Claims can also leave `HELD` the other way: the termination and deactivation cascades of §3.7 and §3.8 deny them, setting `denial_reason` to `ENROLLMENT_TERMINATED` or `ENROLLMENT_DEACTIVATED` as applicable. `DENIED` is terminal.

### 3.7. Revalidation Windows and Deactivation

Every enrollment record carries a revalidation schedule computed from its `last_revalidation_completed_at` and its payer's `revalidation_interval_days`. The base due date is the calendar day of the last completed revalidation plus the interval; for a Medicare payer — one whose `is_medicare` flag is true — the due date then snaps to the last calendar day of the month containing that base, while commercial payers keep the base itself. The `revalidation_window_start` sits sixty days before the `revalidation_due_date`.

The clock sweep walks every record in `ACTIVE` or `PENDING_REVALIDATION`. A record whose due date has passed — the current logical date strictly later than `revalidation_due_date` — is deactivated from either state, moving to `DEACTIVATED`, and the deactivation cascade denies every `HELD` claim of the provider–payer pair with `denial_reason` `ENROLLMENT_DEACTIVATED`. Deactivation is deliberately not retroactive: `RELEASED` claims are left untouched and never recouped. A record still within its window — the current date on or after `revalidation_window_start` but not past the due date — moves from `ACTIVE` to `PENDING_REVALIDATION`; a record already pending stays put until it is revalidated or lapses into deactivation.

Completing a revalidation is the specialist's act, valid only from `PENDING_REVALIDATION`. Invoked on an `ACTIVE` record whose window has not opened it fails with `ERR_REVALIDATION_NOT_DUE`; invoked on a `DEACTIVATED` or `TERMINATED` record it fails with `ERR_INVALID_STATE_TRANSITION`. A successful revalidation returns the record to `ACTIVE`, stamps `last_revalidation_completed_at` from the logical clock, and recomputes `revalidation_due_date` and `revalidation_window_start` from the new baseline — the `ACTIVE → PENDING_REVALIDATION → ACTIVE` cycle may repeat indefinitely. `DEACTIVATED` and `TERMINATED` are terminal record states.

### 3.8. Terminations, Retro-Effective Recoupment, and Reversal

Terminating a single enrollment record is a `ComplianceOfficer` act taking a `termination_effective_date`. The date must be on or after the record's `effective_date`, else `ERR_TERMINATION_DATE_INVALID`; retro-effective dates squarely in the past are explicitly allowed, which is where the money moves. The transition is valid from `ACTIVE` or `PENDING_REVALIDATION` and lands the record in `TERMINATED` with `termination_date` set to the supplied date.

The record-termination cascade then runs over the provider–payer pair's claims. Every `HELD` claim becomes `DENIED` with `denial_reason` `ENROLLMENT_TERMINATED`. Every `RELEASED` claim whose `service_date` is on or after the termination date becomes `RECOUPED`, and each recouped claim is charged a recovery fee of two percent of its `amount_cents`, rounded half up to whole cents and stored as `recoupment_fee_cents`. Both claim sets are processed in service-date order, ties broken by creation order. The fee's rounding order is pinned: the fee is computed per claim and only then summed, never computed once over the summed principals. Two claims of 3,333 cents each therefore yield fees of 67 cents apiece — 134 cents in total — whereas applying the percentage to the combined 6,666 cents and rounding once would yield 133 cents; the per-claim order is the prescribed behavior.

The cascade keeps two ledgers on the record — both zero from the record's creation until a termination runs — and they measure different things. `gross_impacted_cents` sums the principal — `amount_cents` only, fees excluded — over both the `HELD`-to-`DENIED` claims and the `RELEASED`-to-`RECOUPED` claims of the cascade, capturing total claims impact. `net_recouped_cents` sums principal plus fee over only the recouped claims, capturing money actually clawed back; with identical termination data the two figures diverge whenever any held claim is denied or any fee is nonzero. The provider's `recoupment_balance_cents` increases by the cascade's net figure, and at all times that balance equals the sum of principal plus fee over the provider's claims currently in `RECOUPED`.

Terminating the provider is the heavier hammer, available to a `ComplianceOfficer` with a `termination_effective_date` and a `reason`. The provider must be `ACTIVE`, else `ERR_INVALID_STATE_TRANSITION`, and every one of its records in `ACTIVE` or `PENDING_REVALIDATION` must have an `effective_date` on or before the termination date, else `ERR_TERMINATION_DATE_INVALID`. The provider becomes `TERMINATED`, with the date and the reason recorded as `termination_date` and `termination_reason`. The cascade then runs three levels deep: each of those records is terminated with the same termination date, and each record termination fires the full record-termination cascade above — held claims denied, released claims on or after the date recouped with their per-claim fees, and each recoupment lifting the provider's `recoupment_balance_cents` by principal plus fee. After the records, any remaining `HELD` claim of the provider with no covering record is denied with `ENROLLMENT_TERMINATED`, and every in-flight application of the provider — `DRAFT`, `SUBMITTED`, or `PENDING_INFO` — is moved to `WITHDRAWN` by the system. `TERMINATED` is terminal for a provider.

The compensating control for a recoupment made in error is reversal. A `ComplianceOfficer` may reverse a claim that is `RECOUPED`, returning it `RECOUPED → RELEASED`; the provider's `recoupment_balance_cents` is decremented by that claim's principal plus fee, and the claim's `recoupment_fee_cents` is reset to zero. Reversal on a claim in any other state is rejected with `ERR_CLAIM_NOT_RECOUPED`.

## 4. Endpoint Definitions

Operations that create a new resource — a practice group, a provider, a payer, an enrollment application, a delegation agreement, a roster file, or a claim — return `201 Created`. Read operations and all actions that transition or mutate an existing resource return `200 OK`. The complete request and response shapes for each operation are governed by the narratives in §3; this table is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/practice-groups` | Create a practice group | ComplianceOfficer |
| GET | `/api/practice-groups/{id}` | Get a practice group | All roles |
| POST | `/api/practice-groups/{id}/providers` | Create a provider in a practice group; auto-creates the CAQH profile | EnrollmentSpecialist |
| GET | `/api/practice-groups/{id}/providers` | List providers of a practice group | All roles |
| GET | `/api/providers/{id}` | Get a provider, including the computed recoupment balance | All roles |
| POST | `/api/providers/{id}/terminate` | Terminate a provider with a possibly retro-effective date; fires the depth-3 cascade | ComplianceOfficer |
| GET | `/api/providers/{id}/caqh-profile` | Get the provider's CAQH profile (array of length 1) | All roles |
| GET | `/api/providers/{id}/roster-lines` | List roster lines referencing this provider | All roles |
| POST | `/api/payers` | Create a payer with its configuration | ComplianceOfficer |
| GET | `/api/payers/{id}` | Get a payer | All roles |
| POST | `/api/caqh-profiles/{id}/attest` | Attest the CAQH profile; owning provider only; resets the 120-day cycle | Provider |
| POST | `/api/enrollment-applications` | Create an enrollment application in DRAFT | EnrollmentSpecialist |
| GET | `/api/enrollment-applications/{id}` | Get an enrollment application | All roles |
| GET | `/api/enrollment-applications` | List/filter enrollment applications | All roles |
| POST | `/api/enrollment-applications/{id}/submit` | Submit a DRAFT application | EnrollmentSpecialist |
| POST | `/api/enrollment-applications/{id}/request-info` | Payer requests more information | PayerRepresentative |
| POST | `/api/enrollment-applications/{id}/resubmit` | Resubmit after an info request | EnrollmentSpecialist |
| POST | `/api/enrollment-applications/{id}/approve` | Approve; creates the enrollment record and releases eligible held claims | PayerRepresentative |
| POST | `/api/enrollment-applications/{id}/reject` | Reject the application | PayerRepresentative |
| POST | `/api/enrollment-applications/{id}/withdraw` | Withdraw a non-terminal application | EnrollmentSpecialist |
| GET | `/api/enrollment-records/{id}` | Get an enrollment record | All roles |
| GET | `/api/enrollment-records` | List/filter enrollment records | All roles |
| POST | `/api/enrollment-records/{id}/terminate` | Terminate one record; retro-effective dates allowed; fires the record-termination cascade | ComplianceOfficer |
| POST | `/api/enrollment-records/{id}/revalidate` | Complete a revalidation cycle; valid only from PENDING_REVALIDATION | EnrollmentSpecialist |
| POST | `/api/delegation-agreements` | Create a delegated credentialing agreement | ComplianceOfficer |
| GET | `/api/delegation-agreements/{id}` | Get an agreement | All roles |
| GET | `/api/delegation-agreements` | List/filter agreements | All roles |
| POST | `/api/delegation-agreements/{id}/terminate` | Terminate an agreement | ComplianceOfficer |
| POST | `/api/roster-files` | Submit a roster file with its lines; OCC-guarded by the agreement version; supersedes the prior SUBMITTED roster | EnrollmentSpecialist |
| GET | `/api/roster-files/{id}` | Get a roster file including rollup counts | All roles |
| GET | `/api/roster-files` | List/filter roster files | All roles |
| GET | `/api/roster-files/{id}/lines` | List the lines of a roster file, ordered by line_index ascending | All roles |
| POST | `/api/roster-files/{id}/lines/{lineId}/confirm` | Payer confirms a line with its confirmed effective date; date equality decides CONFIRMED vs DISCREPANCY | PayerRepresentative |
| POST | `/api/roster-files/{id}/lines/{lineId}/reject` | Payer rejects a line | PayerRepresentative |
| POST | `/api/roster-files/{id}/lines/{lineId}/resolve` | Specialist resolves a DISCREPANCY line: accept the confirmed date or decline | EnrollmentSpecialist |
| POST | `/api/roster-files/{id}/reconcile` | Compliance sign-off closing a fully adjudicated roster; never the original submitter | ComplianceOfficer |
| POST | `/api/claims` | Receive a claim; initial status computed by the coverage test | EnrollmentSpecialist |
| GET | `/api/claims/{id}` | Get a claim | All roles |
| GET | `/api/claims` | List/filter claims | All roles |
| POST | `/api/claims/{id}/reverse-recoupment` | Reverse a recoupment: RECOUPED to RELEASED, fee zeroed, balance decremented | ComplianceOfficer |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock; monotonic; fires the CAQH, revalidation, and agreement sweeps | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every domain error identifier and its HTTP status; the only further identifier the API can emit is `ERR_INTERNAL` (HTTP 500) for an unexpected server fault, delivered in the same envelope (§2.2). Trigger conditions are specified where each error naturally arises in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROFILE_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_ROSTER_LINE_NOT_PENDING` | 409 |
| `ERR_CLAIM_NOT_RECOUPED` | 409 |
| `ERR_REVALIDATION_NOT_DUE` | 409 |
| `ERR_PROVIDER_TERMINATED` | 409 |
| `ERR_CAQH_ATTESTATION_NOT_CURRENT` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_PROVIDER_GROUP_MISMATCH` | 422 |
| `ERR_NO_ACTIVE_ENROLLMENT` | 422 |
| `ERR_RETRO_WINDOW_EXCEEDED` | 422 |
| `ERR_TERMINATION_DATE_INVALID` | 422 |
| `ERR_FUTURE_SERVICE_DATE` | 422 |
| `ERR_DUPLICATE_NPI` | 409 |
| `ERR_APPLICATION_IN_FLIGHT` | 409 |
| `ERR_ENROLLMENT_OVERLAP` | 409 |
| `ERR_AGREEMENT_OVERLAP` | 409 |
| `ERR_EMPTY_ROSTER` | 422 |
| `ERR_CLOCK_REGRESSION` | 422 |
