# Eviction Judgment Execution API — Product Requirements Document

## 1. Introduction

Landlords who must recover possession of a rental unit through the courts face a long, deadline-driven process: serve the correct statutory notice, wait out a jurisdiction-specific cure period, prepare and pay for a filing package, arrange service of process on every named defendant, attend hearings, survive or settle mediation, obtain a judgment, wait out the appeal window, and finally schedule a sheriff's lockout — all while post-judgment money collection and statutory obligations toward the tenant's abandoned personal property continue in parallel. This document specifies a landlord-side API that manages that entire lifecycle for eviction cases brought under three statute profiles — California (`CA`), Texas (`TX`), and Ohio (`OH`) — each with its own cure periods, filing-fee tiers, interest rates, appeal windows, writ fees, hearing lead times, and storage rules.

The system is built around an Eviction Case aggregate whose state machine runs from `DRAFT` through notice, filing, service, hearing, judgment, and writ stages to one of four terminal outcomes (`EXECUTED`, `SETTLED`, `DISMISSED`, `CURED`). Because the workflow spans several independent court actors, the API enforces strict segregation of duties: a landlord may not serve process on their own case, the clerk who accepts a filing fee may not enter the judgment, and lockout actions bind to the specific deputy assigned. All temporal rules — cure deadlines, appeal windows, writ validity, storage eligibility — are evaluated against a server-held logical clock so that the entire lifecycle is deterministically testable. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Six roles are recognized, spelled exactly as follows: `PlatformAdmin`, `Landlord`, `CourtClerk`, `ProcessServer`, `SheriffDeputy`, and `Mediator`. A request with missing headers, or whose role is not one of these declared values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the per-endpoint role assignments are listed in §4.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord` record; ownership checks on any resource whose aggregate chain references a landlord compare that chain's `landlord_id` to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `CourtClerk`, `ProcessServer`, `SheriffDeputy`, or `Mediator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such identifiers on resources it mutates — for example as `accepted_by_clerk_id`, `entered_by_clerk_id`, `clerk_user_id`, `filed_by_clerk_id`, `server_user_id`, or `recorded_by` — but it never compares them against any entity's `id`. Two actor-binding rules do compare the opaque identifier against stored input fields: a mediation outcome may only be recorded by the operator whose `X-User-ID` equals the referral's `mediator_id`, and a lockout execution or cancellation may only be recorded by the operator whose `X-User-ID` equals the writ's `deputy_id` (see §2.9).

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — Landlord, RentalUnit, Tenancy, EvictionCase, Notice, FilingPackage, Hearing, TenantAnswer, MediationReferral, Judgment, Writ, PropertyStorageRecord, and RentalHistoryReport — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- **`version` (integer):** a system-managed integer that increments with every modification; it backs optimistic concurrency control where that mechanism applies (§2.8).

Two resources are deliberately immutable ledger-style records and break this pattern: a **ServiceAttempt** and a **CollectionEntry** each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them, because neither resource is ever modified after creation.

### 2.5. The Logical Clock and the Ops-Run Sweep

Every temporal rule in this document — cure deadlines, future-date prohibitions, hearing lead times, writ validity, lockout windows, storage accrual, reporting windows — evaluates the word "now" against a server-held **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it advances only when an operator with the `PlatformAdmin` role invokes the test-driving clock capability with a target instant `to_iso8601`; the response reports the new clock reading as `current_utc`. The logical clock never falls back to wall-clock time.

Several lifecycle transitions are time-triggered rather than user-triggered. A `CourtClerk` performs an **ops-run checkpoint sweep**, which applies five steps in a fixed order: first, every notice still `PENDING` whose cure deadline has passed (the logical clock strictly later than `cure_deadline`) becomes `EXPIRED`, and each such notice's case advances from `NOTICE_ACTIVE` to `NOTICE_EXPIRED`; second, every judgment in `ENTERED` whose `appeal_deadline` has been reached or passed becomes `FINAL`; third, every writ still `ISSUED` whose `expires_on` has passed becomes `EXPIRED`, and its case falls back from `WRIT_ISSUED` to `JUDGMENT_ENTERED`; fourth, every writ still `SCHEDULED` whose lockout window has closed without execution (the logical clock later than `window_end`) returns to `ISSUED` with its deputy and window fields cleared, and its case returns from `LOCKOUT_SCHEDULED` to `WRIT_ISSUED`; fifth, every storage record still `STORED` whose `disposal_eligible_on` has passed becomes `DISPOSABLE`. The sweep responds with a summary object containing the five integer counters `notices_expired`, `judgments_finalized`, `writs_expired`, `writs_unscheduled`, and `storage_records_disposable`.

### 2.6. Money, Dates, and Jurisdictional Schedules

All monetary values are integer cents. No monetary calculation involves fractional cents: the single rounding step in the entire system is the prejudgment-interest per-diem computation (§3.6), which rounds half-up to a whole cent exactly once before any multiplication by days. Day counts and defendant counts are integers. Date-only fields use the `YYYY-MM-DD` calendar format; all instants are ISO 8601 UTC timestamps, and deadlines that close out a calendar date are pinned at 23:59:59Z on that date.

Behavior across the three supported jurisdictions — `CA`, `TX`, and `OH`, recorded on each unit as its `jurisdiction_code` — is governed by statutory schedules: notice cure periods, filing-fee tiers, the annual prejudgment interest rate, the appeal window length, the writ fee, the hearing lead time, and the storage daily fee, billing mode, and disposal period. Each schedule is stated in the workflow subsection that consumes it (§3.2 through §3.7) rather than centralized here.

### 2.7. Validation Order and Nested Resource Resolution

Every request is evaluated against an ordered validation ladder, and the first failing rung determines the error returned. The rungs, in evaluation order:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared; failure yields `ERR_UNAUTHENTICATED`.
2. **Endpoint authorization** — the role is permitted for this endpoint per §4; failure yields `ERR_FORBIDDEN`.
3. **Existence** — every resource referenced in the path exists, validated strictly left to right (unit, tenancy, case, notice, package, hearing, answer, referral, judgment, writ, storage record, collection entry, report, landlord, in the order the identifiers appear in the path); the first missing identifier yields `ERR_NOT_FOUND` and no later identifier is examined.
4. **Ownership and actor binding** — landlord ownership of the aggregate chain, mediator binding, and deputy binding (§2.9); failures yield `ERR_NOT_OWNER`, `ERR_NOT_ASSIGNED_MEDIATOR`, or `ERR_NOT_ASSIGNED_DEPUTY`.
5. **Request body shape** — required fields present, types correct, enum members valid, and conditional requirements met (for example `claimed_rent_owed_cents` is required exactly when the notice type is `PAY_OR_QUIT`); failure yields `ERR_VALIDATION`.
6. **Optimistic concurrency** — the `expected_case_version` check on notice drafting (§2.8); failure yields `ERR_STALE_VERSION`.
7. **State admissibility** — the target entity is in a status that permits the operation (the case-state gate of each transition, a `PENDING` notice, a `DRAFT` package, a `SCHEDULED` hearing, a `PENDING` referral, a writ in `ISSUED` or `SCHEDULED` as applicable, a storage record in `STORED` or `DISPOSABLE`); failure yields `ERR_INVALID_STATE`.
8. **Business safety** — segregation-of-duties rules, appeal finality, possession, and storage-disposal eligibility, in that relative order.
9. **Business constraints** — uniqueness and compatibility rules: the one-open-case and unit-occupancy rules, notice-type compatibility, the one-scheduled-hearing rule, defendant membership and uniqueness, the one-active-writ rule, deputy day capacity, and judgment uniqueness.
10. **Temporal rules** — future-date prohibitions, the cure window, hearing window, lead time and courtroom overlap, lockout window validity and openness, and the rental-history reporting window.
11. **Referential rules** — report trigger existence, correction-target validity, and reversal-target validity.
12. **Fiscal rules** — cure sufficiency, fee overpayment, the paid-fee precondition on review, the exact writ fee, the exact reclaim charge, and the outstanding-balance limits on collection entries.

Where several of these rules guard a single endpoint, the subsections of §3 restate the evaluation order locally for that endpoint.

### 2.8. Optimistic Concurrency Control on Notice Drafting

Exactly one write operation in the system is protected by optimistic concurrency control: the creation of a statutory notice against an eviction case, which also covers drafting a replacement notice that supersedes the previous one. The request must carry `expected_case_version`, a non-optional input holding the case `version` the client last observed. If another writer has advanced the case's version since that observation — for example by creating a notice of their own, which itself supersedes the prior notice and increments the case `version` by exactly 1 — the values will differ, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from drafting against a case it has not re-read. No other endpoint accepts a version field; every other write proceeds without an optimistic-concurrency check.

### 2.9. Segregation of Duties and Actor Binding

Four independence rules run across role boundaries. First, landlord ownership: on every write performed in the `Landlord` role, the `X-User-ID` presented must equal the `landlord_id` of the aggregate chain being mutated — the case, notice, filing package, judgment, tenancy, or unit the write touches; a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). Second, a party may not serve process: the operator recording a service attempt must not be the landlord who owns the case, or the attempt is rejected with `ERR_SOD_PARTY_CANNOT_SERVE` (HTTP 403). Third, fee acceptance and judgment entry must be performed by different clerks: the clerk entering a judgment must differ from the clerk recorded as `accepted_by_clerk_id` on the case's `ACCEPTED` filing package, or entry is rejected with `ERR_SOD_FEE_JUDGMENT` (HTTP 409). Fourth, actor binding on delegated work: a mediation outcome is only accepted from the operator whose `X-User-ID` equals the referral's `mediator_id` (`ERR_NOT_ASSIGNED_MEDIATOR`, HTTP 403), and a lockout execution or cancellation is only accepted from the operator whose `X-User-ID` equals the writ's assigned `deputy_id` (`ERR_NOT_ASSIGNED_DEPUTY`, HTTP 403).

### 2.10. Cascading State Propagation

State changes propagate automatically along the aggregate chain, without any separate client request on the downstream resource. The deepest cascade is lockout execution: executing a writ moves its case to `EXECUTED`, which in turn ends the tenancy (status `ENDED`, `ended_at` stamped), which in turn returns the rental unit to `VACANT`. Mediation propagates sideways: referring an answer to mediation stays the case's scheduled hearing, and recording the mediation outcome cancels that stayed hearing. Time-driven propagation runs through the ops-run sweep (§2.5): notice expiry advances the case, writ expiry reverts the case from `WRIT_ISSUED` to `JUDGMENT_ENTERED`, and a lapsed lockout window unwinds both writ and case. Drafting a replacement notice retires the prior one to `SUPERSEDED`. Recording a tenant cure promotes both the notice and the case to their cured outcomes. Every such mutation refreshes `updated_at` and increments `version` on each affected entity that carries those fields.

## 3. Business Logic & Workflows

### 3.1. Portfolios: Landlords, Units, and Tenancies

A `PlatformAdmin` onboards each landlord by registering a record with a `legal_name` and a `contact_email`. From that point the landlord manages their own portfolio. Creating a rental unit requires the owning `landlord_id`, the unit's `jurisdiction_code` (one of `CA`, `TX`, or `OH`), a `street_address`, and a `unit_label` designator such as "4B". A new unit begins life with `status` `VACANT`.

Placing a tenant creates a Tenancy. The landlord supplies the `unit_id`, the `tenant_full_name` (this is a landlord-side system; the tenant is never an API role), a positive `monthly_rent_cents`, and the `lease_start_date`. The `lease_end_date` is optional and defaults to null, which represents a month-to-month arrangement. A tenancy is created with `status` `ACTIVE` and `ended_at` null. Creation is refused with `ERR_UNIT_OCCUPIED` (HTTP 409) when any other `ACTIVE` tenancy already exists for the unit; on success the unit moves from `VACANT` to `OCCUPIED`. The unit returns to `VACANT` only through the lockout-execution cascade described in §3.7.

### 3.2. Opening a Case and the Statutory Notice Period

An eviction begins when a landlord opens a case against an `ACTIVE` tenancy, supplying the `tenancy_id` and a `case_reason` of `NONPAYMENT`, `LEASE_VIOLATION`, or `SEVERE`. Only one case per tenancy may be open at a time: if any case for that tenancy exists in a non-terminal status — anything other than `EXECUTED`, `SETTLED`, `DISMISSED`, or `CURED` — creation is rejected with `ERR_CASE_ALREADY_OPEN` (HTTP 409). A new case starts in `DRAFT`; the server mints its `case_number` in the format EV-<year>-<zero-padded sequence> and denormalizes the `landlord_id` from the tenancy's unit at creation, where it remains immutable thereafter. A landlord can review their docket through the case list, optionally filtered by `landlord_id`, `tenancy_id`, or `status`.

The first filing act on a `DRAFT` case is drafting the statutory notice, which moves the case to `NOTICE_ACTIVE`. The notice's `notice_type` must be compatible with the case reason: `PAY_OR_QUIT` is lawful only for `NONPAYMENT`, `CURE_OR_QUIT` only for `LEASE_VIOLATION`, and `UNCONDITIONAL_QUIT` only for `SEVERE`; an incompatible pairing is rejected with `ERR_NOTICE_TYPE_MISMATCH` (HTTP 422). The payload carries the `served_on` calendar date, which must not lie in the future relative to the logical clock (`ERR_DATE_IN_FUTURE`, HTTP 422), plus type-conditional fields: `claimed_rent_owed_cents`, a positive amount required exactly for `PAY_OR_QUIT`, and `violation_description`, required exactly for `CURE_OR_QUIT`; violating these conditional requirements is an `ERR_VALIDATION` failure. On a `NOTICE_ACTIVE` case the same drafting action creates a replacement notice: the previously `PENDING` notice becomes `SUPERSEDED`, the new notice starts `PENDING`, and the case remains `NOTICE_ACTIVE`. Either way the case's `version` increments by exactly 1, and because the action is optimistic-concurrency protected (§2.8), a request whose `expected_case_version` no longer matches is rejected with `ERR_STALE_VERSION` before any of these effects occur. The checks on notice drafting are evaluated in ladder order: ownership first, then body shape including the conditional fields, then the stale-version check, then the case-state gate, then notice-type compatibility, and finally the future-date rule.

Each notice's statutory cure period is computed at creation from the unit's jurisdiction and the notice type, and stored as `statutory_cure_days`. In `CA` the period is 3 days for `PAY_OR_QUIT`, 3 days for `CURE_OR_QUIT`, and 0 days for `UNCONDITIONAL_QUIT`; in `TX` it is 3, 5, and 0 days respectively; in `OH` it is 5, 7, and 0 days. The `cure_deadline` falls at 23:59:59Z on the calendar date that is `statutory_cure_days` days after `served_on`. A notice expires only when the logical clock is strictly later than `cure_deadline`; at the exact deadline instant the notice remains curable. Expiry itself is not client-driven: the ops-run sweep (§2.5) moves an overdue `PENDING` notice to `EXPIRED` and advances its case from `NOTICE_ACTIVE` to `NOTICE_EXPIRED`.

While the notice is `PENDING` and the deadline has not passed, the landlord may record a tenant cure. For a `PAY_OR_QUIT` notice the payload's `paid_amount_cents` must be at least the claimed `claimed_rent_owed_cents`, or the attempt is rejected with `ERR_CURE_AMOUNT_INSUFFICIENT` (HTTP 422). For a `CURE_OR_QUIT` notice the payload must affirm `violation_cured` as true. An `UNCONDITIONAL_QUIT` notice is never curable, and any cure attempt after the deadline — or on an unconditional notice at any time — is rejected with `ERR_CURE_WINDOW_CLOSED` (HTTP 409). A successful cure stamps `cured_at`, moves the notice to `CURED`, and moves the case from `NOTICE_ACTIVE` to the terminal `CURED` status.

A landlord may also walk away: voluntary dismissal, with an optional `reason` recorded on the case as `dismiss_reason`, is available while the case is in `DRAFT`, `NOTICE_ACTIVE`, `NOTICE_EXPIRED`, `FILING_REJECTED`, `FILED`, `SERVICE_COMPLETE`, `HEARING_SCHEDULED`, `ANSWERED`, or `HEARING_CONCLUDED`, and moves the case to the terminal `DISMISSED` status. Once the case has reached `JUDGMENT_ENTERED` or beyond — or is already terminal — dismissal is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. The Filing Package and Court Fees

Once the notice period has run, the landlord prepares a Filing Package for the case: the total `claimed_amount_cents` sought in the complaint (a positive amount), between 1 and 5 unique, non-empty `defendant_names`, a `jury_demanded` flag, and an `efiled` flag selecting the electronic variant when true and the paper variant when false. The package is created in `DRAFT` status with `fee_paid_cents` at zero and `fee_status` `UNPAID`.

The court fee is computed once at creation and frozen on the package as `filing_fee_cents`, immutable thereafter. The computation starts from a jurisdictional base tiered on the claimed amount, where a claim exactly at a tier ceiling prices at that tier: in `CA`, a claim of 250000 cents or less prices at a 24000-cent base, a claim of 1000000 cents or less at 32000, and any larger claim at 43500; in `TX` the tiers are 18500 cents up to a 200000-cent claim, 26000 up to 800000, and 35000 above; in `OH` they are 15000 cents up to 150000, 21000 up to 500000, and 30000 above. A surcharge of 2500 cents is added for each named defendant, and a flat 15000 cents is added when a jury is demanded. The variant then adjusts the total: a paper filing adds a 750-cent counter-service surcharge, while an electronic filing subtracts a 1000-cent e-filing discount — and if that discount would drive the fee below zero, the fee floors at zero.

The landlord pays the fee in one or more payments, each carrying an `amount_cents` that is added to `fee_paid_cents`; a payment that would push the cumulative total above the frozen `filing_fee_cents` is rejected with `ERR_FEE_OVERPAYMENT` (HTTP 422). After each payment the `fee_status` is recomputed: `UNPAID` when nothing has been paid, `PARTIAL` while the cumulative total is short of the fee, and `PAID` once it equals the fee.

Review belongs to a `CourtClerk`, who submits a `decision` of `ACCEPT` or `REJECT`. Reviewing a package that is not `DRAFT` fails the state gate with `ERR_INVALID_STATE`, and reviewing one whose `fee_status` is not yet `PAID` is rejected with `ERR_FEE_UNPAID` (HTTP 422). An `ACCEPT` decision — available while the case is `NOTICE_EXPIRED` or `FILING_REJECTED` — marks the package `ACCEPTED`, records the acting clerk as `accepted_by_clerk_id`, stamps `accepted_at` (the anchor for the FILING rental-history report window, §3.9), and moves the case to `FILED`. A `REJECT` decision stores the supplied `rejection_reason` on the package, marks it `REJECTED`, and moves the case to `FILING_REJECTED`; from there the landlord may prepare a fresh package and the cycle repeats, with acceptance moving the case to `FILED` and another rejection leaving it `FILING_REJECTED`.

### 3.4. Service of Process

A `FILED` case must be served on every named defendant before it can be heard. Service attempts are recorded by a `ProcessServer` or a `SheriffDeputy` — never by the landlord, because a party may not serve process on their own case; a recorder whose `X-User-ID` equals the case's `landlord_id` is rejected with `ERR_SOD_PARTY_CANNOT_SERVE`. Each attempt names a `defendant_name`, a `method` of `PERSONAL`, `SUBSTITUTED`, or `POST_AND_MAIL`, a `result` of `SERVED` or `FAILED`, and the `served_at` instant, which must not lie in the future (`ERR_DATE_IN_FUTURE`). The recorder's `X-User-ID` and `X-User-Role` are captured on the record as `server_user_id` and `server_role`. Because a ServiceAttempt is an immutable record, it carries only `id` and `created_at` — no `updated_at`, no `version`.

Two membership rules protect the defendant set, evaluated after the state gate and the party-service prohibition: the named `defendant_name` must be one of the `defendant_names` on the case's `ACCEPTED` package (`ERR_DEFENDANT_UNKNOWN`, HTTP 422), and a defendant who already has a `SERVED` attempt on the case may not be served again (`ERR_DEFENDANT_ALREADY_SERVED`, HTTP 409). The case accumulates the distinct names with a `SERVED` attempt in `served_defendant_names`; `FAILED` attempts add nothing. A `SERVED` attempt that does not complete the set leaves the case in `FILED`; at the moment the served set covers every name in the accepted package's `defendant_names` — a cardinality comparison, since duplicates are impossible — the case advances from `FILED` to `SERVICE_COMPLETE`, and `service_completed_at` is set to the `served_at` of the completing attempt.

### 3.5. Hearings, Tenant Answers, and Mediation

With service complete, a `CourtClerk` schedules a hearing by supplying the `courtroom`, `start_at`, and `end_at`; the scheduling clerk is recorded as `clerk_user_id`. Four scheduling rules apply, in this order after the state gate. The case may hold at most one `SCHEDULED` hearing at a time (`ERR_HEARING_ALREADY_SCHEDULED`, HTTP 409). The window must be well-formed — `end_at` later than `start_at` (`ERR_HEARING_WINDOW_INVALID`, HTTP 422). The hearing date must respect the statutory lead time: the calendar date of `start_at` must be at least the calendar date of `service_completed_at` plus the jurisdiction's lead days — 10 in `CA`, 8 in `TX`, 12 in `OH` (`ERR_HEARING_LEAD_TIME`, HTTP 422). Finally, courtroom double-booking is forbidden: the half-open interval from `start_at` up to but not including `end_at` must not intersect any other `SCHEDULED` hearing in the same courtroom, though two hearings whose windows merely touch — one ending exactly when the other begins — do not conflict (`ERR_COURTROOM_OVERLAP`, HTTP 409). A successful scheduling creates the hearing in `SCHEDULED` and moves the case from `SERVICE_COMPLETE` to `HEARING_SCHEDULED`.

Plans change. A continuance, requested by a clerk with an optional `reason`, marks the original `SCHEDULED` hearing `CONTINUED` and creates a replacement hearing — with its own `courtroom`, `start_at`, and `end_at` — validated by exactly the same four scheduling rules; the replacement starts `SCHEDULED` and the case remains `HEARING_SCHEDULED`. A hearing that was `CANCELLED` after a failed mediation likewise frees the clerk to schedule a fresh hearing, returning the case to `HEARING_SCHEDULED`.

The tenant's side of the story enters when a clerk records an answer on a `HEARING_SCHEDULED` case: a non-empty `defense_codes` list drawn from `PAYMENT_TENDERED`, `HABITABILITY`, `RETALIATION`, and `PROCEDURAL`, plus a `mediation_requested` flag. The answer is created `FILED`, the recording clerk is captured as `filed_by_clerk_id`, and the case moves to `ANSWERED`.

When an answer in `FILED` status carries `mediation_requested` as true, a clerk may refer it to mediation, naming a `mediator_id` — an opaque identifier for the court-appointed mediator — and a `session_date`. Referral creates the MediationReferral in `PENDING`, permanently linked to the answer through its `answer_id`, moves the answer to `REFERRED`, moves the case to `MEDIATION_PENDING`, and stays the case's `SCHEDULED` hearing if one exists (`SCHEDULED` → `STAYED`). The outcome may only be recorded by the operator whose `X-User-ID` equals the referral's `mediator_id` (`ERR_NOT_ASSIGNED_MEDIATOR`), and only while the referral is `PENDING`; the payload's `outcome` is `SETTLED` or `FAILED`, with optional `notes` preserved as `outcome_notes` alongside the `outcome_recorded_at` stamp. A `SETTLED` outcome moves the referral to `SETTLED`, the answer to `RESOLVED`, any stayed hearing to `CANCELLED`, and the case to the terminal `SETTLED` status. A `FAILED` outcome moves the referral to `FAILED`, the answer to `RETURNED`, any stayed hearing to `CANCELLED`, and loops the case back to `HEARING_SCHEDULED`, where a fresh hearing may be scheduled. This answer–mediation cycle can repeat: `HEARING_SCHEDULED` → `ANSWERED` → `MEDIATION_PENDING` → `HEARING_SCHEDULED`.

Whether or not an answer was filed, the hearing itself concludes when a clerk marks it held — optionally with `notes` — provided the hearing is `SCHEDULED` and the case is `HEARING_SCHEDULED` or `ANSWERED`. The hearing becomes `HELD` and the case advances to `HEARING_CONCLUDED`.

### 3.6. Judgment: The Money Award and Appeal Finality

On a `HEARING_CONCLUDED` case a `CourtClerk` enters the judgment. At most one Judgment may ever exist for a case — a second attempt is rejected with `ERR_JUDGMENT_EXISTS` (HTTP 409) — and the segregation-of-duties rule of §2.9 applies: the entering clerk must differ from the `accepted_by_clerk_id` recorded when the filing fee was accepted (`ERR_SOD_FEE_JUDGMENT`). The entry payload carries `possession_granted`, the four money components `rent_awarded_cents`, `damages_cents`, `late_fee_cents`, and `court_costs_cents` (each zero or greater), and the `oldest_unpaid_due_date` that anchors prejudgment interest.

The derived money fields are computed at entry. The interest principal is the sum of the rent awarded and the damages. The days overdue are the calendar days between `oldest_unpaid_due_date` and the date of entry, floored at zero so a due date after entry yields none. The per-diem interest is the principal multiplied by the jurisdiction's annual rate — ten percent in `CA`, six percent in `TX`, eight percent in `OH` — divided by 365, and that per-diem amount is rounded half-up to a whole cent before anything else happens; the `interest_cents` is then that rounded per-diem amount multiplied by the days overdue. This order is pinned: rounding the per-diem first and then multiplying is mandatory, because rounding the whole product in one step yields different cents. The `total_awarded_cents` is the sum of rent, damages, late fees, court costs, and interest, added in exactly that order, and the `outstanding_balance_cents` starts equal to it. The entry also stamps `entered_at`, records the acting clerk as `entered_by_clerk_id`, and computes the `appeal_deadline` as `entered_at` plus the jurisdictional appeal window — 5 days in `CA`, 5 days in `TX`, 10 in `OH`. The judgment begins in `ENTERED` status and the case moves to `JUDGMENT_ENTERED`; reading the case's judgment yields an array of zero or one element.

Finality arrives with time: the ops-run sweep flips an `ENTERED` judgment to `FINAL` once the logical clock has reached or passed its `appeal_deadline`. Only a `FINAL` judgment supports the writ stage that follows. Independently, a judgment in either `ENTERED` or `FINAL` becomes `SATISFIED` the moment collections drive its outstanding balance to zero (§3.8), with `satisfied_at` stamped at that instant.

### 3.7. Writ of Possession, Lockout, and Property Storage

Once the judgment is final and awards possession, the landlord may request a writ. Four gates guard the request, evaluated after the generic ladder rungs: the judgment must be `FINAL` — a request during the appeal window is rejected with `ERR_APPEAL_WINDOW_OPEN` (HTTP 409); the judgment must have granted possession (`possession_granted` true), else `ERR_NO_POSSESSION_GRANTED` (HTTP 422); no other writ for the same judgment may already be active in `REQUESTED`, `ISSUED`, or `SCHEDULED` (`ERR_WRIT_ACTIVE_EXISTS`, HTTP 409); and the `writ_fee_paid_cents` in the request must exactly equal the jurisdictional writ fee — 4000 cents in `CA`, 3500 in `TX`, 2500 in `OH` — with any mismatch rejected as `ERR_WRIT_FEE_MISMATCH` (HTTP 422). A writ is created `REQUESTED`, linked to the judgment through its `judgment_id`, denormalizing its `case_id` from the judgment and its `unit_id` through the case's tenancy at creation; the denormalized pair remains immutable and identifies the premises being executed on.

Issuance is a clerk action on a `REQUESTED` writ, and the appeal-finality gate applies again: the judgment must be `FINAL` or issuance fails with `ERR_APPEAL_WINDOW_OPEN`. Issuance stamps `issued_at` and computes `expires_on` as the issuance instant plus the jurisdiction's writ validity period; the writ becomes `ISSUED` and the case advances from `JUDGMENT_ENTERED` to `WRIT_ISSUED`.

A `SheriffDeputy` then schedules the lockout, supplying the `deputy_id` of the assigned deputy and the `window_start` and `window_end` instants. The window must be valid: `window_start` not in the past, `window_end` later than `window_start`, and `window_end` no later than `expires_on` (`ERR_WRIT_WINDOW_INVALID`, HTTP 422). Deputy workload is capped: scheduling is rejected with `ERR_DEPUTY_DAY_CAPACITY` (HTTP 409) when the assigned deputy already has 3 `SCHEDULED` writs on the UTC calendar date of `window_start` — so the third booking on a day succeeds and the fourth fails. A valid scheduling moves the writ to `SCHEDULED` and the case to `LOCKOUT_SCHEDULED`.

Cancellation unwinds cleanly. The assigned deputy — and only that deputy, bound by `X-User-ID` equal to the writ's `deputy_id` (`ERR_NOT_ASSIGNED_DEPUTY`) — may cancel with an optional `reason`, returning the writ to `ISSUED`, clearing its `deputy_id`, `window_start`, and `window_end`, freeing the deputy's day-slot, and returning the case to `WRIT_ISSUED`. The ops-run sweep performs the same unwind when a scheduled window lapses without execution. Should an `ISSUED` writ sit past its `expires_on`, the sweep instead moves it to the terminal `EXPIRED` and drops the case back to `JUDGMENT_ENTERED`, where the landlord may request a fresh writ.

Execution is the point of no return. The assigned deputy executes while the writ is `SCHEDULED` and the logical clock sits at or after `window_start` and at or before `window_end`, and not after `expires_on`; execution outside that envelope is rejected with `ERR_LOCKOUT_WINDOW_NOT_OPEN` (HTTP 409). The payload may carry an `items_summary` describing the tenant's personal property. On execution the writ becomes `EXECUTED` with `executed_at` stamped, and a PropertyStorageRecord springs into existence in `STORED` status, linked to the writ via `writ_id` and denormalizing `case_id`, with `stored_at` set to the execution instant and `items_summary` taken from the payload. The cascade then runs (§2.10): the case moves from `LOCKOUT_SCHEDULED` to the terminal `EXECUTED`, the tenancy moves from `ACTIVE` to `ENDED` with `ended_at` stamped, and the unit returns from `OCCUPIED` to `VACANT`.

Storage obligations follow the unit's jurisdiction. The record's `daily_fee_cents` is 1500 in `CA`, 1000 in `TX`, and 800 in `OH`, and its `billing_mode` is `CALENDAR_INCLUSIVE` in `CA` but `ELAPSED_24H` in `TX` and `OH`. The `accrued_charge_cents` is always computed against the current logical clock: under `CALENDAR_INCLUSIVE` the chargeable days are the calendar dates touched by the storage interval, counting both the stored date and the current date — a partial first day and a partial final day each count as a full day; under `ELAPSED_24H` the chargeable days are the elapsed 24-hour periods with any partial period rounded up, so a record twenty-three hours old charges one day where the inclusive-calendar mode would charge two. The charge is the chargeable days multiplied by the daily fee. The `disposal_eligible_on` instant is `stored_at` plus the statutory storage period — 15 days in `CA`, 14 in `TX`, 30 in `OH` — and the ops-run sweep moves a `STORED` record to `DISPOSABLE` once that instant has passed.

The tenant may reclaim property at any time while the record is `STORED` or `DISPOSABLE`, but the deputy records the reclaim only when the payload's `charge_paid_cents` exactly equals the `accrued_charge_cents` at the current clock; any mismatch is rejected with `ERR_STORAGE_CHARGE_MISMATCH` (HTTP 422). A successful reclaim locks `final_charge_cents` to the accrued amount, freezes `accrued_charge_cents` to the same figure, and moves the record to `RECLAIMED`. Disposal of unclaimed property is permitted only from `DISPOSABLE` — disposing before the statutory period has elapsed is a compliance violation rejected with `ERR_DISPOSAL_NOT_ELIGIBLE` (HTTP 409) — and moves the record to `DISPOSED`. Once a record is `RECLAIMED` or `DISPOSED`, its `accrued_charge_cents` reads as 0.

### 3.8. Post-Judgment Collections and Satisfaction

Money collection runs against the judgment through CollectionEntry records created by the landlord under the target `judgment_id` — immutable ledger rows carrying only `id` and `created_at` among the common fields, each capturing the recorder's `X-User-ID` as `recorded_by`. Every entry has an `entry_type` of `PAYMENT`, `REVERSAL`, or `WRITE_OFF` and a positive `amount_cents`, and entries are applied to the judgment's balances in chronological order of creation.

A `PAYMENT` allocates across five buckets in a fixed priority order — court costs first, then late fees, then damages, then interest, then rent. Each bucket's remainder starts at the awarded amount for that component and shrinks as payments apply. The payment walks the buckets in order, applying to each bucket the lesser of its remainder and the amount still unallocated, until the payment is exhausted; the five applied amounts are recorded on the entry as its `allocation` object. A payment larger than the judgment's current `outstanding_balance_cents` is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422), though an exact payoff is allowed.

A `REVERSAL` undoes a previous payment: its `reversal_of_id` must reference a `PAYMENT` entry on the same judgment that has not already been reversed (`ERR_REVERSAL_TARGET_INVALID`, HTTP 422), and its amount must exactly equal the target payment's amount (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`). The reversal adds the amount back to the outstanding balance, re-crediting the buckets in reverse priority order — rent first, then interest, damages, late fees, and court costs last — and the target payment's `reversed_by_id` is set to point at the reversal. A `WRITE_OFF` reduces the outstanding balance without touching any bucket and is likewise capped at the current outstanding balance, with excess rejected as `ERR_PAYMENT_EXCEEDS_OUTSTANDING`. For both `REVERSAL` and `WRITE_OFF` entries the `allocation` object is zero-filled.

Each entry stores the judgment's balance immediately after its application as `resulting_outstanding_cents`. The outstanding balance itself is the total award minus the sum of payment amounts, plus the sum of reversal amounts, minus the sum of write-off amounts, taken over the judgment's entries that have not been reversed. When a payment, reversal, or write-off drives that balance to zero, the judgment becomes `SATISFIED` and `satisfied_at` is stamped — whether the judgment was still `ENTERED` or already `FINAL`.

### 3.9. Rental-History Reporting

The closing obligation is reporting to the rental-history bureau. A landlord files a RentalHistoryReport against a tenancy, choosing a `report_type` of `FILING`, `JUDGMENT`, `SATISFACTION`, or `CORRECTION`; the server mints a `bureau_reference` in the format RHR-<sequence>, denormalizes the `landlord_id` from the tenancy's unit, and anchors the report's `event_at` to the underlying trigger event. For a `FILING` report the anchor is the `accepted_at` of the first `ACCEPTED` filing package on a case of that tenancy; for `JUDGMENT` it is the judgment's `entered_at`; for `SATISFACTION` it is the judgment's `satisfied_at`; for `CORRECTION` it inherits the referenced report's `event_at`.

Two referential gates apply. The trigger event must exist for the tenancy: a `FILING` report requires an `ACCEPTED` package on a case of the tenancy, a `JUDGMENT` report requires a judgment, and a `SATISFACTION` report requires a judgment in `SATISFIED` status; a missing trigger is rejected with `ERR_REPORT_EVENT_MISSING` (HTTP 422). Timeliness is enforced with a 30-day window: a `FILING`, `JUDGMENT`, or `SATISFACTION` report must be filed no later than 30 days after its `event_at`, else `ERR_REPORT_WINDOW_LAPSED` (HTTP 422); `CORRECTION` reports are exempt from this window.

A correction names its target via `reference_report_id`, required exactly when the report type is `CORRECTION`. The target must exist, must belong to the same tenancy, must not itself be a `CORRECTION`, and must not already be superseded; any violation is rejected with `ERR_CORRECTION_TARGET_INVALID` (HTTP 422). Filing the correction sets the referenced report's `superseded` flag to true, preserving the audit chain while marking which report currently speaks for the event.

## 4. Endpoint Definitions

Endpoints that create a new resource — registering a landlord, opening a case, drafting a notice, recording a service attempt, and so on — return `201 Created`. Endpoints that modify an existing resource in place — review decisions, cures, dismissals, lockout actions, sweeps — return `200 OK`. All list and read endpoints return `200 OK`. Readers should reconstruct each endpoint's full request and response semantics from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/landlords` | Register a landlord | PlatformAdmin |
| GET | `/api/landlords/{id}` | Read a landlord | PlatformAdmin, Landlord, CourtClerk |
| GET | `/api/landlords` | List landlords (paginated) | PlatformAdmin, CourtClerk |
| POST | `/api/units` | Create a rental unit for a landlord | Landlord |
| GET | `/api/units/{id}` | Read a unit | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| GET | `/api/landlords/{id}/units` | List a landlord's units | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/tenancies` | Create a tenancy on a VACANT unit; unit becomes OCCUPIED | Landlord |
| GET | `/api/tenancies/{id}` | Read a tenancy | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| GET | `/api/units/{id}/tenancies` | List tenancies of a unit | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/cases` | Open an eviction case (DRAFT) on an ACTIVE tenancy | Landlord |
| GET | `/api/cases/{id}` | Read a case (includes version for OCC) | Landlord, CourtClerk, ProcessServer, SheriffDeputy, Mediator, PlatformAdmin |
| GET | `/api/cases` | List cases with filters | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/tenancies/{id}/cases` | List cases of a tenancy | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/cases/{id}/dismiss` | Voluntary dismissal; forbidden once judgment entered | Landlord |
| POST | `/api/cases/{id}/notices` | Create or supersede the statutory notice; OCC via expected_case_version | Landlord |
| GET | `/api/notices/{id}` | Read a notice | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/cases/{id}/notices` | List notices of a case | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/notices/{id}/record-cure` | Record a tenant cure within the cure window | Landlord |
| POST | `/api/cases/{id}/filing-packages` | Prepare a filing package; computes and freezes the filing fee | Landlord |
| GET | `/api/filing-packages/{id}` | Read a filing package | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/cases/{id}/filing-packages` | List packages of a case | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/filing-packages/{id}/fee-payments` | Record a court-fee payment; overpayment rejected | Landlord |
| POST | `/api/filing-packages/{id}/review` | Clerk review; ACCEPT requires fee PAID and moves case to FILED | CourtClerk |
| POST | `/api/cases/{id}/service-attempts` | Record a service-of-process attempt by a non-party | ProcessServer, SheriffDeputy |
| GET | `/api/cases/{id}/service-attempts` | List service attempts of a case | Landlord, CourtClerk, ProcessServer, SheriffDeputy, PlatformAdmin |
| POST | `/api/cases/{id}/hearings` | Schedule a hearing with lead-time and courtroom-overlap checks | CourtClerk |
| GET | `/api/hearings/{id}` | Read a hearing | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/cases/{id}/hearings` | List hearings of a case | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/hearings/{id}/continuance` | Continue a SCHEDULED hearing; creates a replacement | CourtClerk |
| POST | `/api/hearings/{id}/conclude` | Mark a hearing HELD; case moves to HEARING_CONCLUDED | CourtClerk |
| POST | `/api/cases/{id}/answers` | Record the tenant answer and defenses; case moves to ANSWERED | CourtClerk |
| GET | `/api/answers/{id}` | Read an answer | Landlord, CourtClerk, Mediator, PlatformAdmin |
| GET | `/api/cases/{id}/answers` | List answers of a case | Landlord, CourtClerk, Mediator, PlatformAdmin |
| POST | `/api/answers/{id}/mediation-referrals` | Refer an answer to mediation; stays the scheduled hearing | CourtClerk |
| GET | `/api/referrals/{id}` | Read a referral | Landlord, CourtClerk, Mediator, PlatformAdmin |
| GET | `/api/answers/{id}/mediation-referrals` | List referrals of an answer | Landlord, CourtClerk, Mediator, PlatformAdmin |
| POST | `/api/referrals/{id}/outcome` | Mediator records SETTLED or FAILED | Mediator |
| POST | `/api/cases/{id}/judgment` | Enter judgment (possession and money award) | CourtClerk |
| GET | `/api/judgments/{id}` | Read a judgment | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| GET | `/api/cases/{id}/judgment` | Read the case's judgment (array of 0 or 1) | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| POST | `/api/judgments/{id}/writs` | Request a writ of possession; requires FINAL judgment and exact fee | Landlord |
| GET | `/api/writs/{id}` | Read a writ | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| GET | `/api/judgments/{id}/writs` | List writs of a judgment | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| POST | `/api/writs/{id}/issue` | Clerk issues the writ; sets issued_at and expires_on | CourtClerk |
| POST | `/api/writs/{id}/schedule-lockout` | Deputy schedules the lockout window (max 3 per deputy per day) | SheriffDeputy |
| POST | `/api/writs/{id}/cancel-lockout` | Cancel a scheduled lockout; writ returns to ISSUED | SheriffDeputy |
| POST | `/api/writs/{id}/execute` | Execute the lockout inside the window; creates the storage record | SheriffDeputy |
| GET | `/api/writs/{id}/storage-records` | List storage records created by a writ (0 or 1) | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| GET | `/api/storage-records/{id}` | Read a storage record (charge computed at current clock) | Landlord, CourtClerk, SheriffDeputy, PlatformAdmin |
| POST | `/api/storage-records/{id}/reclaim` | Tenant reclaims property against the exact accrued charge | SheriffDeputy |
| POST | `/api/storage-records/{id}/dispose` | Dispose of unclaimed property once DISPOSABLE | SheriffDeputy |
| POST | `/api/judgments/{id}/collection-entries` | Record a PAYMENT, REVERSAL, or WRITE_OFF against the judgment | Landlord |
| GET | `/api/judgments/{id}/collection-entries` | List collection entries of a judgment | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/collection-entries/{id}` | Read a collection entry | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/collection-entries/{id}/reversals` | List reversal entries targeting this entry | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/tenancies/{id}/rental-history-reports` | File a FILING, JUDGMENT, SATISFACTION, or CORRECTION report | Landlord |
| GET | `/api/rental-history-reports/{id}` | Read a rental-history report | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/tenancies/{id}/rental-history-reports` | List reports of a tenancy | Landlord, CourtClerk, PlatformAdmin |
| GET | `/api/rental-history-reports/{id}/corrections` | List corrections referencing this report | Landlord, CourtClerk, PlatformAdmin |
| POST | `/api/ops/runs` | Ops-run checkpoint sweep (notices, judgments, writs, lockouts, storage) | CourtClerk |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_MEDIATOR` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_DEPUTY` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SOD_PARTY_CANNOT_SERVE` | 403 Forbidden |
| `ERR_SOD_FEE_JUDGMENT` | 409 Conflict |
| `ERR_APPEAL_WINDOW_OPEN` | 409 Conflict |
| `ERR_NO_POSSESSION_GRANTED` | 422 Unprocessable Entity |
| `ERR_DISPOSAL_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CASE_ALREADY_OPEN` | 409 Conflict |
| `ERR_UNIT_OCCUPIED` | 409 Conflict |
| `ERR_NOTICE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_HEARING_ALREADY_SCHEDULED` | 409 Conflict |
| `ERR_DEFENDANT_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_DEFENDANT_ALREADY_SERVED` | 409 Conflict |
| `ERR_WRIT_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_DEPUTY_DAY_CAPACITY` | 409 Conflict |
| `ERR_JUDGMENT_EXISTS` | 409 Conflict |
| `ERR_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_CURE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_HEARING_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_HEARING_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_COURTROOM_OVERLAP` | 409 Conflict |
| `ERR_WRIT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_LOCKOUT_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_REPORT_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_REPORT_EVENT_MISSING` | 422 Unprocessable Entity |
| `ERR_CORRECTION_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_REVERSAL_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_CURE_AMOUNT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FEE_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_FEE_UNPAID` | 422 Unprocessable Entity |
| `ERR_WRIT_FEE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STORAGE_CHARGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
