# Anesthesia Group Staffing & Billing API — Product Requirements Document

## 1. Introduction

An anesthesia physician group runs a fundamentally different operating model than a hospital ward: every morning the group's schedulers must distribute a fixed pool of anesthesiologists, nurse anesthetists, and anesthesiologist assistants across several contracted facilities, decide who personally performs each case and who medically directs it, and then — once the day is over — turn that choreography into payer-ready claims and hospital-subsidy accounting. Two regulatory and financial pressures dominate. Medicare's TEFRA rules pay full "medical direction" rates only when a directing anesthesiologist documents seven specific participation steps and never supervises more than four concurrent rooms; failure collapses the claim into much less favorable modifier codes. Meanwhile the hospitals that depend on the group's call coverage pay stipends — call-night pay, late-stay pay, standby pay for cancelled cases — that must be accrued, capped daily and monthly, and reconciled to the cent.

This document specifies the API for that operating backbone, mounted under `/anesthesia-ops`. It covers daily rosters and their publication lifecycle, case scheduling and execution, the assignment handshake between schedulers and providers, TEFRA direction attestations with mandatory segregation of duties, an anesthesia-unit charge engine with modifier-driven rates and a pinned rounding order, a stipend ledger with two-level cap waterfalls, and a compliance audit subsystem that scores risk on both a forward-looking and a chronological basis. All "current time" decisions in the system are driven by a deterministic logical clock rather than the wall clock, so that sweeps (credential suspension, call completion) and date-sensitive rules (same-day starts, cancellation notice tiers) are reproducible. Concurrency on the three most contended records — cases, rosters, and provider credentials — is serialized through optimistic version checks rather than locks.

The intended readers are the engineers implementing the service and the group's product and compliance staff verifying that the encoded rules match the contracts the group has signed with its hospitals and payers.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which the user acts. A request missing either header, or presenting a role value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `GroupAdministrator` — the group's business-office administrator. Owns configuration (sites, providers, fee schedules, stipend agreements), credential maintenance, stipend-entry voids, and the logical clock. Identity is opaque: when `X-User-Role` is `GroupAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server never compares it to any entity's `id`.
- `Scheduler` — the group's scheduling coordinator. Builds rosters, schedules and reschedules cases, proposes and cancels assignments, manages call coverage, and records case start, completion, and cancellation. Identity is opaque: when `X-User-Role` is `Scheduler`, `X-User-ID` is not tied to any persisted entity and is never compared to any entity's `id`.
- `AttendingAnesthesiologist` — an anesthesiologist member of the group. Accepts or declines the physician's own assignments, submits TEFRA attestations for the physician's own directed cases, and verifies or rejects other physicians' attestations. Identity is entity-backed: when `X-User-Role` is `AttendingAnesthesiologist`, `X-User-ID` is the `id` of the acting `Provider`, and ownership checks on any resource that references a provider — the `provider_id` of an assignment being accepted or declined, the `physician_id` of an attestation being submitted — compare that foreign-key field to `X-User-ID`.
- `CRNA` — a certified registered nurse anesthetist member of the group. Accepts or declines the CRNA's own assignments. Identity is entity-backed: when `X-User-Role` is `CRNA`, `X-User-ID` is the `id` of the acting `Provider`, and ownership checks compare the assignment's `provider_id` to `X-User-ID`. CRNAs cannot see stipend-ledger endpoints.
- `BillingSpecialist` — the group's billing staff. Manages the claim lifecycle from draft through payment, denial, and write-off. Identity is opaque: `X-User-ID` is never compared to any entity's `id`.
- `ComplianceAuditor` — an independent compliance reviewer. Runs roster audits, resolves or dismisses findings, and closes audits. Identity is opaque: `X-User-ID` is never compared to any entity's `id`.

Two authorization refinements sit on top of raw role membership. For entity-backed roles, a mismatch between `X-User-ID` and the resource's owning provider reference is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). For attestation review, the rule is inverted — the reviewer must *not* be the attesting physician — and a review submitted by the attesting physician is rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403). This segregation-of-duties rule means an attestation can never be both submitted and verified by the same physician.

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

List endpoints accept two query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. Results are always sorted by `created_at` in ascending order — the oldest record first. The `meta` object of a list response carries `limit`, `offset`, `total_count` (the full count of matching records, not just the page), and `has_more` (whether further pages exist beyond this one).

### 2.4. The Logical Clock and Minute-of-Day Timekeeping

The server maintains a logical clock, and every rule that says "now" — case start and completion stamps, cancellation notice, release timing, credential sweeps — consults that clock and nothing else. Before any administrator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time at any point afterward. A `GroupAdministrator`-only capability advances the clock by supplying a `to_iso8601` timestamp and returns the resulting `current_utc`. Setting the clock triggers two sweeps in the same request: every provider whose earlier credential-or-DEA expiry date falls strictly before the new clock date is suspended, and every still-scheduled call assignment whose window end lies strictly in the past is auto-completed with its stipend accrual (both cascades are detailed in §2.7 and §3.4).

Within a day, time is expressed as integer minutes from midnight. Start-of-window fields (`scheduled_start_minute`, `window_start_minute`, and the roster's `scheduled_day_end_minute`) range from 0 through 1438 inclusive; end-of-window fields (`scheduled_end_minute`, `window_end_minute`) must be strictly later than their start and no later than 1439. Calendar dates such as `service_date`, `effective_from`, `effective_to`, `credential_expires_on`, and `dea_expires_on` use the `YYYY-MM-DD` form. A "clock date" comparison always means the calendar date of the logical clock; a "clock minute-of-day" is the minute-of-day component of the logical clock.

### 2.5. Resource Identity, Timestamps, and Optimistic Concurrency

Every persisted resource carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, the same format, refreshed on every mutation; and `version`, an integer that starts at its initial value on creation and increments by exactly one on every mutation of that resource — including mutations driven by cascades, so a case whose completion closes out three assignments increments each assignment's `version` individually.

Four write operations are guarded by optimistic concurrency control, and each names its guard field explicitly:

- Proposing a case assignment requires `expected_case_version`, carrying the client's last observed `version` of the target case. If the case's current version has advanced since that observation — for example because another writer has just created a same-role assignment and thereby superseded the prior one — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Rescheduling a case likewise requires `expected_case_version`, and a mismatch with the case's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a roster's staffing requirements requires `expected_roster_version`; a value that no longer matches the roster's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a provider's credential dates requires `expected_provider_version`; a value that no longer matches the provider's current `version` — which a clock-sweep suspension may have advanced — is rejected with `ERR_STALE_VERSION` (HTTP 412).

The stale-version check is evaluated after the target resource's own state preconditions and before any business rule. Endpoints not listed above take no version field at all.

### 2.6. Three Interval Algebras: Half-Open, Closed-Minute, and Closed-Date

The system deliberately uses three different overlap semantics, and confusing them is the single most common scheduling bug this API is designed to prevent.

Case intervals — both scheduled (`scheduled_start_minute`, `scheduled_end_minute`) and actual (`actual_start_minute`, `actual_end_minute`) — are **half-open**: the start minute belongs to the interval and the end minute does not. Two case intervals conflict only when each begins strictly before the other ends; two intervals that merely touch at an endpoint — one ending at minute 600, another beginning at minute 600 — do not conflict.

Call-coverage windows (`window_start_minute`, `window_end_minute`) are **closed intervals**: both endpoint minutes belong to the window. Two windows for the same provider on the same service date conflict when they share any minute at all, including a single shared endpoint minute — a window ending at 600 and another beginning at 600 do conflict here, in deliberate contrast to case intervals.

Stipend-agreement windows (`effective_from`, `effective_to`) are **closed date intervals** scoped to one site: the end date must not precede the start date, both boundary dates are covered, and two agreements for the same site may not share even a single calendar date.

### 2.7. Credential Currency and Provider Suspension

A provider is registered with `full_name`, a `provider_type` of `ANESTHESIOLOGIST`, `CRNA`, or `AA`, a National Provider Identifier in `npi` (unique across providers — re-registering an existing identifier is rejected with `ERR_DUPLICATE_PROVIDER_NPI`), and two expiry dates: `credential_expires_on` for board credentials and `dea_expires_on` for the DEA registration. Both expiry dates are valid *through* the named date: a provider may serve on the expiry date itself, and only a service date strictly later than an expiry violates currency. New providers begin `ACTIVE`.

Suspension is system-driven, not request-driven. When the logical clock is set to a date strictly later than the earlier of a provider's two expiry dates, the provider transitions `ACTIVE → SUSPENDED` and its `version` increments by one. A `SUSPENDED` provider cannot confirm assignments (§3.3). Reinstatement happens through the credential-update operation: when a `GroupAdministrator` patches both expiry dates so that both are on or after the current clock date, a suspended provider returns to `ACTIVE`. The patch and the reinstatement together increment `version` exactly once. If the patch leaves either expiry still before the clock date, the provider remains `SUSPENDED`, but the patch itself still succeeds and still increments `version`.

Shortening credentials is itself a compliance event. When a credential patch leaves any of the provider's `PROPOSED` or `CONFIRMED` case assignments with a roster `service_date` strictly later than the earlier of the two new expiry dates, the system raises a `CREDENTIAL_LAPSE` finding (severity `MINOR`) on that roster's `OPEN` compliance audit, creating the audit if none exists, and the audit's scores recompute as described in §3.9.

### 2.8. Validation Pipeline and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed pipeline so that the surfaced error is deterministic:

1. **Header presence and role validity** — missing `X-User-ID`, missing `X-User-Role`, or an undeclared role value yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — a valid role not listed for the endpoint yields `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Request schema** — required fields present, types correct, enum values valid, no unknown fields, dates well-formed; violations yield `ERR_INVALID_REQUEST`. This layer also enforces fields that are required only for a specific transition, such as `cancellation_reason` on cancel, `rejection_reason` on reject, `denial_reason` on record-denial, and `paid_amount_cents` on record-payment.
   - **3b. Minute-window sanity** — on case creation, case rescheduling, and call-window creation, the start/end minute pair must satisfy the §2.4 bounds (start at least 0, end strictly after start, end at most 1439); violations yield `ERR_INVALID_TIME_WINDOW`.
4. **Existence** — path identifiers are validated left to right, then body foreign keys in declared input order (`site_id`, then `roster_id`, then `provider_id`, then `case_id`, then `physician_id`). Unknown resources surface as `ERR_SITE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_ROSTER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CALL_ASSIGNMENT_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_STIPEND_ENTRY_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, or `ERR_FINDING_NOT_FOUND`, each HTTP 404. A case's `procedure_code` that matches no fee-schedule row is rejected at this layer with `ERR_UNKNOWN_PROCEDURE_CODE` (HTTP 404).
5. **Ownership and segregation of duties** — `ERR_OWNERSHIP_MISMATCH` for entity-backed actors acting on resources they do not own; `ERR_SELF_REVIEW_FORBIDDEN` for attestation self-review.
6. **State gates** — evaluated in the sub-order: (6a) roster lifecycle first, then (6b) the target resource's own state precondition, then (6c) clock-date and actual-time consistency. All are HTTP 409 and are named at their workflows in §3.
   - **6d. Stale version** — the §2.5 optimistic-concurrency check, `ERR_STALE_VERSION` (HTTP 412), evaluated after the resource's own state preconditions and before any business rule.
7. **Provider safety** — credential currency (7a, `ERR_CREDENTIAL_EXPIRED`) is evaluated before the supervision-ratio check (7b, `ERR_SUPERVISION_RATIO_EXCEEDED`).
8. **Uniqueness and duplicates** — `ERR_DUPLICATE_ROSTER`, `ERR_DUPLICATE_PROVIDER_NPI`, `ERR_DUPLICATE_PROCEDURE_CODE`, `ERR_DUPLICATE_ATTESTATION`, and `ERR_DUPLICATE_CLAIM`.
9. **Interval conflicts** — `ERR_PROVIDER_DOUBLE_BOOKED`, `ERR_CALL_WINDOW_OVERLAP`, and `ERR_AGREEMENT_WINDOW_OVERLAP`.
10. **Rest buffer** — `ERR_INSUFFICIENT_REST`.
11. **Fiscal gate** — the contracted-maximum check at mark-ready, `ERR_CHARGE_EXCEEDS_MAX` (HTTP 402).
12. **TEFRA completeness** — the seven-step check, `ERR_TEFRA_STEPS_INCOMPLETE` (HTTP 422), evaluated after ownership and state: a non-owner submitting an incomplete attestation receives `ERR_OWNERSHIP_MISMATCH`, not the TEFRA error.

### 2.9. Units, Money, and Rounding Discipline

Anesthesia charges are computed in **units** carried to exactly one decimal place, rounding half up whenever a fraction must be resolved. Money is carried in whole cents, also rounding half up — an exact half-cent rounds away from zero. Where a charge pipeline requires several rounding steps (units, then multiplication, then a split), the order of those steps is part of the contract and is pinned in §3.7; implementations must not re-order, coalesce, or pre-round intermediate values differently. Conversion factors used by the charge engine are 8,000 cents ($80.00) per unit for personally performed physician work, 8,001 cents ($80.01) per unit for verified medical direction, 7,500 cents ($75.00) per unit for a CRNA or AA working without direction, and 4,000 cents ($40.00) per unit for the flat supervision fallback.

## 3. Business Logic & Workflows

### 3.1. Roster Construction, Publication, and Locking

Everything that happens on a given day at a given facility hangs off a **daily roster**. Before any roster can exist, a `GroupAdministrator` registers the facility itself: a site carries only a `name` and a system-managed `status` that is always `ACTIVE` in this version of the API, the value reserved for future archival. A `Scheduler` then creates a roster by naming the `site_id`, the `service_date`, the planned `required_primary_slots` (the number of confirmed hands-on providers the day needs, zero or more), and the `scheduled_day_end_minute` against which late-stay pay will later be measured. One roster may exist per site per calendar date; a second roster for the same `site_id` and `service_date` is rejected with `ERR_DUPLICATE_ROSTER`. A new roster begins with `lifecycle` `DRAFT` and `posture` `UNDERSTAFFED`.

Posture is never stored as an input; it is re-derived on every read. A roster reads `STAFFED` exactly when the count of `CONFIRMED` `CASE_PRIMARY` assignments across the roster's cases reaches `required_primary_slots`, and `UNDERSTAFFED` otherwise — so a single acceptance or cancellation can flip the derived posture without any write to the roster itself.

Publishing moves the roster `DRAFT → PUBLISHED` and is the gate that opens the day: assignments, call windows, and case starts all refuse to act on an unpublished roster. Publishing is defined only out of `DRAFT`; attempting it from any other lifecycle is rejected with `ERR_ROSTER_NOT_DRAFT`. Unpublishing reverts `PUBLISHED → DRAFT`, but only while nothing has clinically happened — every case on the roster must still be `SCHEDULED` or `CANCELLED`, and the presence of any `IN_PROGRESS` or `COMPLETED` case rejects the revert with `ERR_CASES_OUTSTANDING`. Locking moves `PUBLISHED → LOCKED` and is stricter still: every case on the roster must be terminal (`COMPLETED` or `CANCELLED`), otherwise the lock is rejected with `ERR_CASES_OUTSTANDING`. Locking is defined only out of `PUBLISHED`. `LOCKED` is terminal, and it is the event that opens billing — claims may be submitted only after their case's roster is locked.

A locked roster is frozen against further scheduling mutation: creating cases on it, rescheduling its cases, proposing new assignments, unpublishing it, and patching its staffing requirements are all rejected with `ERR_ROSTER_LIFECYCLE_LOCKED`. While the roster is `DRAFT` or `PUBLISHED`, a `Scheduler` may adjust `required_primary_slots` or `scheduled_day_end_minute` through the roster-update operation; the request must carry `expected_roster_version` per §2.5, each accepted patch increments the roster's `version`, and the derived `posture` simply re-derives against the new targets on the next read. Roster lists may be filtered by `site_id`, `service_date`, or `lifecycle`.

### 3.2. Case Scheduling and Rescheduling

A `Scheduler` places a case on a roster by supplying the `roster_id`, a `procedure_code`, the patient's ASA `physical_status` (one of `P1`, `P2`, `P3`, `P4`, `P5`, `P6`), an optional `emergency_flag` (default false), and the planned `scheduled_start_minute` and `scheduled_end_minute`. The `procedure_code` is a lookup key, not an identifier: it must match an existing fee-schedule row's `procedure_code`, and an unknown code is rejected with `ERR_UNKNOWN_PROCEDURE_CODE`. Fee-schedule rows themselves are maintained by a `GroupAdministrator`, who creates them with the lookup `procedure_code` (globally unique — a repeat is `ERR_DUPLICATE_PROCEDURE_CODE`), the procedure's `base_units` (from 1 to 50), the payer-contracted `contracted_max_cents` ceiling used later at claim review, and an optional `description`; contract renegotiation amends `base_units` or `contracted_max_cents` in place, each amendment incrementing the row's `version`.

Case creation is permitted while the roster is `DRAFT` or `PUBLISHED`; on a `LOCKED` roster it is rejected with `ERR_ROSTER_LIFECYCLE_LOCKED`. New cases begin `SCHEDULED`, with `actual_start_minute`, `actual_end_minute`, `cancellation_reason`, `cancellation_notice_minutes`, `provisional_charge_cents`, and `final_charge_cents` all null.

Rescheduling is the OCC-guarded case patch described in §2.5: the caller supplies `expected_case_version` along with a new `scheduled_start_minute`, `scheduled_end_minute`, or both. Only a `SCHEDULED` case may be rescheduled — attempts against a case in any other state are rejected with `ERR_CASE_NOT_SCHEDULED` — and a case on a `LOCKED` roster cannot be rescheduled at all (`ERR_ROSTER_LIFECYCLE_LOCKED`). A reschedule that violates the minute-window bounds is rejected with `ERR_INVALID_TIME_WINDOW`. Because moving a case can invalidate commitments already made against it, an accepted reschedule re-runs the full safety battery of §3.3 for the case's `PROPOSED` and `CONFIRMED` assignments — supervision ratio for directing assignments, double-booking and rest-buffer checks for the primary — and, when a primary is currently `CONFIRMED`, recomputes `provisional_charge_cents` against the new scheduled minutes using the same forward-looking math as assignment acceptance. Case lists may be filtered by `roster_id` or `status`.

### 3.3. Staffing a Case: Assignments, Credentials, and Safety Gates

A case is staffed by proposing assignments against it. Each proposal names a `provider_id` and an `assignment_role` — `CASE_PRIMARY` for the hands-on anesthetist or `CASE_DIRECTING` for the medically directing anesthesiologist — and must carry `expected_case_version` per §2.5, since proposal churn mutates the case (each accepted proposal increments the case's `version` by one). Proposals are accepted only while the case's roster is `PUBLISHED` (otherwise `ERR_ROSTER_NOT_PUBLISHED`; on a `LOCKED` roster, `ERR_ROSTER_LIFECYCLE_LOCKED`) and the case itself is `SCHEDULED` (otherwise `ERR_CASE_NOT_SCHEDULED`). The new assignment begins `PROPOSED`, and its `roster_id` is denormalized from the case at creation so that roster-scoped filtering and posture derivation never chase joins.

Only one live assignment may exist per role per case. Creating a new assignment with the same `assignment_role` as an existing `PROPOSED` or `CONFIRMED` assignment on the same case automatically transitions the older one to `SUPERSEDED` (bumping its `version`); if the superseded assignment was a `CONFIRMED` `CASE_PRIMARY`, the case's `provisional_charge_cents` returns to null and stays there until the replacement confirms.

Four safety gates stand between proposal and a valid lineup, applied in the §2.8 order. First, **credential currency**: the provider must be credential-current for the service date — the roster's `service_date` must not be strictly later than either `credential_expires_on` or `dea_expires_on` — else the proposal is rejected with `ERR_CREDENTIAL_EXPIRED`. Second, for a `CASE_DIRECTING` proposal, the **supervision ratio**: the system collects the physician's `PROPOSED` and `CONFIRMED` `CASE_DIRECTING` assignments on cases sharing the roster's `service_date`, adds the candidate case's scheduled interval, and computes the peak overlap across that set of half-open intervals (intervals touching at an endpoint do not overlap). If adding the candidate would push the physician's peak directed concurrency above four rooms, the proposal is rejected with `ERR_SUPERVISION_RATIO_EXCEEDED`. This is an aggregate-capacity rule, not a pairwise rule: four pairwise-overlapping rooms are allowed, a fifth concurrent room is not. A physician also may not direct a case whose scheduled interval overlaps one of the same physician's `PROPOSED` or `CONFIRMED` `CASE_PRIMARY` intervals on that date — personally performing and directing at once — which is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`. Third, for a `CASE_PRIMARY` proposal, **double-booking**: the provider's `PROPOSED` and `CONFIRMED` `CASE_PRIMARY` intervals across all rosters on the same service date, plus — when the provider is an `ANESTHESIOLOGIST` — that physician's `PROPOSED` and `CONFIRMED` `CASE_DIRECTING` intervals, are checked pairwise under half-open semantics; any pair where each interval begins before the other ends is a conflict rejected with `ERR_PROVIDER_DOUBLE_BOOKED`, while intervals that merely abut do not conflict. Fourth, the **rest buffer**: for each of the provider's call assignments on the same service date, in any status, whose `window_end_minute` falls at or before the case's `scheduled_start_minute`, the gap between window end and case start must be at least eight hours (480 minutes); a strictly smaller gap rejects the proposal with `ERR_INSUFFICIENT_REST`, while a gap of exactly 480 minutes is allowed.

The provider named on a proposal answers it. Acceptance — permitted to `AttendingAnesthesiologist` and `CRNA` actors whose `X-User-ID` equals the assignment's `provider_id`, with mismatches rejected as `ERR_OWNERSHIP_MISMATCH` — moves the assignment `PROPOSED → CONFIRMED`. Acceptance re-runs the safety checks against the world as it now stands: the provider must still be `ACTIVE` (a suspended provider is rejected with `ERR_PROVIDER_SUSPENDED`) and credential-current for the service date (else `ERR_CREDENTIAL_EXPIRED`), and the assignment must still be `PROPOSED` (else `ERR_ASSIGNMENT_NOT_PROPOSED`). When a `CASE_PRIMARY` assignment confirms, the case's `provisional_charge_cents` is computed as a forward-looking estimate: scheduled duration in minutes run through the unit math of §3.7, multiplied by the contextually optimistic conversion factor — 8,000 cents per unit when the primary is an `ANESTHESIOLOGIST` with no `CONFIRMED` directing assignment on the case, 7,500 cents when the primary is a `CRNA` or `AA` with no confirmed directing assignment, and 8,001 cents when a `CASE_DIRECTING` assignment is `CONFIRMED` (optimistically assuming the direction attestation will verify) — rounded half-up to whole cents. Declining moves the assignment from `PROPOSED` to the terminal `DECLINED` state under the same ownership rule, with no further checks.

A `Scheduler` may also cancel an assignment outright. Cancellation is available while the assignment is `PROPOSED` or `CONFIRMED` and its case is still `SCHEDULED`; once the case is `IN_PROGRESS` or terminal, the attempt is rejected with `ERR_ASSIGNMENT_NOT_CANCELLABLE`. Cancelling a `CONFIRMED` `CASE_PRIMARY` nulls the case's `provisional_charge_cents`, since no confirmed hands-on provider remains. Notably, scheduler-side reassignment never generates standby pay — standby stipends arise only from case cancellation (§3.6). Assignment lists may be filtered by `case_id`, `provider_id`, `roster_id`, `status`, or `assignment_role`.

### 3.4. Call Coverage Windows and Early Release

Separate from case staffing, a `Scheduler` may place a provider on call for a roster by naming the `roster_id`, the `provider_id`, and a closed `window_start_minute`/`window_end_minute` pair. Call windows require the roster to be `PUBLISHED`; any other lifecycle, `LOCKED` included, is rejected with `ERR_ROSTER_NOT_PUBLISHED`. A provider may hold at most one window covering any given minute on a service date: because call windows are closed intervals (§2.6), any two windows for the same provider on the same `service_date` — across all rosters — that share even a single endpoint minute are rejected with `ERR_CALL_WINDOW_OVERLAP`. New call assignments begin `SCHEDULED`, with `released_at_minute` null.

Call assignments end in one of two ways. Natural completion is clock-driven: when the logical clock is set strictly past a `SCHEDULED` window's end (past the service date's `window_end_minute`), the sweep transitions the assignment `SCHEDULED → COMPLETED`, bumps its `version`, and — when a stipend agreement covers the roster's site and service date — accrues a `CALL` ledger entry for the full `call_stipend_cents`, with the applied amount equal to the raw amount because call pay is exempt from the daily cap (§3.8).

Early release is deliberate: a `Scheduler` releases a provider mid-window, moving the assignment from `SCHEDULED` to the terminal `RELEASED` state and stamping `released_at_minute` with the clock minute-of-day. Release is gated on the clock date equaling the roster's `service_date` (else `ERR_CLOCK_DATE_MISMATCH`) and the clock minute falling strictly inside the window — at or before the start, or at or after the end, the request is rejected with `ERR_CALL_NOT_RELEASABLE`, and natural completion must be left to the clock sweep. Released coverage pays by served fraction: let the served minutes be `released_at_minute` minus `window_start_minute`, and the window length be `window_end_minute` minus `window_start_minute`. Serving at least half the window earns the full `call_stipend_cents`; serving at least one quarter but less than half earns half the stipend, rounded half-up to whole cents; serving less than a quarter earns nothing and no ledger entry is created. Call-assignment lists may be filtered by `roster_id`, `provider_id`, or `status`.

### 3.5. TEFRA Medical-Direction Attestations

When an anesthesiologist medically directs a case rather than personally performing it, full direction rates are payable only if the physician documents all seven TEFRA participation steps. A **direction attestation** binds one case to one physician: it is created with a `case_id` and a `physician_id` (which must reference a provider of type `ANESTHESIOLOGIST`), and only one attestation may exist per pair — a duplicate is rejected with `ERR_DUPLICATE_ATTESTATION`. Either a `Scheduler` or the physician personally may create it; when an `AttendingAnesthesiologist` creates it, the `physician_id` must equal the caller's `X-User-ID`, else `ERR_OWNERSHIP_MISMATCH`. A new attestation begins `IN_PROGRESS`, with `submitted_count` at zero, `rejection_reason` null, and all seven step flags false by default.

The seven steps, each carried as its own boolean, are: `step_preanesthetic_exam` (performed the pre-anesthetic exam and evaluation), `step_prescribes_plan` (prescribed the anesthesia plan), `step_participates_key_portions` (personally participated in the most demanding portions, induction and emergence), `step_ensures_qualified_personnel` (ensured any procedures not personally performed were done by a qualified individual), `step_monitors_course` (monitored the course of anesthesia administration at frequent intervals), `step_available_for_emergencies` (remained physically present and available for immediate diagnosis and treatment of emergencies), and `step_post_anesthesia_care` (provided indicated post-anesthesia care).

Submission is the physician's own act — the caller's `X-User-ID` must equal the attestation's `physician_id`, else `ERR_OWNERSHIP_MISMATCH` — and is available from either `IN_PROGRESS` or `REJECTED` (any other status yields `ERR_ATTESTATION_NOT_SUBMITTABLE`). All seven step flags supplied in the request must be true; an incomplete set is rejected with `ERR_TEFRA_STEPS_INCOMPLETE` (HTTP 422), and per the §2.8 pipeline a caller who is not the attesting physician receives the ownership error even when the steps are incomplete. Each successful submission moves the attestation to `SUBMITTED`, increments `submitted_count` by one, clears any prior `rejection_reason` to null, and increments `version`.

Review is performed by a *different* anesthesiologist: verification and rejection both require the caller to be an `AttendingAnesthesiologist` whose `X-User-ID` differs from the attestation's `physician_id`, and a self-review is rejected with `ERR_SELF_REVIEW_FORBIDDEN`. Both review actions require the attestation to be `SUBMITTED` (else `ERR_ATTESTATION_NOT_SUBMITTED`). Verification moves `SUBMITTED → VERIFIED`, the terminal state that unlocks full direction rates at case completion (§3.7). Rejection moves `SUBMITTED → REJECTED`, records the supplied `rejection_reason`, and returns the attestation to the physician, who may revise and resubmit — each such resubmission again increments `submitted_count`. Attestation lists may be filtered by `case_id`, `physician_id`, or `status`.

### 3.6. Case Execution: Start, Completion, and Cancellation Cascades

On the day of service, a `Scheduler` starts the case, moving it `SCHEDULED → IN_PROGRESS` and stamping `actual_start_minute` from the clock minute-of-day. Starting is permitted only while the roster is `PUBLISHED` (else `ERR_ROSTER_NOT_PUBLISHED`), the case is `SCHEDULED` (else `ERR_CASE_NOT_SCHEDULED`), and the clock date equals the roster's `service_date` (else `ERR_CLOCK_DATE_MISMATCH`). The version increments with the transition.

Completion is the system's richest cascade, moving `IN_PROGRESS → COMPLETED`. It requires the clock date to equal the roster's `service_date` (else `ERR_CLOCK_DATE_MISMATCH`) and the clock minute-of-day to be strictly later than `actual_start_minute` (else `ERR_INVALID_ACTUAL_MINUTES`); a case not `IN_PROGRESS` is rejected with `ERR_CASE_NOT_IN_PROGRESS`. On acceptance, the following all happen within the same request:

1. `actual_end_minute` is stamped from the clock minute-of-day and the case's `version` increments.
2. Every `PROPOSED` or `CONFIRMED` assignment on the case closes out to `COMPLETED`, each bumping its own `version`.
3. One `DRAFT` billing claim is auto-created per assignment that was `CONFIRMED` at the moment of completion — assignments still `PROPOSED` at completion generate no claim at all. Each claim's modifier and charge are computed from **actual** minutes per §3.7.
4. The case's `final_charge_cents` is set to the sum of the created claims' `charge_cents`.
5. If a `CASE_DIRECTING` assignment was `CONFIRMED` at completion and the attestation matching that case and directing physician is not `VERIFIED` (missing, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` all count as not verified), the system raises a `TEFRA_GAP` finding (severity `MAJOR`) on the roster's `OPEN` compliance audit, creating an `OPEN` audit first if none exists; the audit's `period_score` recomputes as the finding bubbles up (§3.9).
6. Late-stay pay is evaluated for the completing primary: if the case's completed `CASE_PRIMARY` provider holds no call assignment of any status on the roster's date (on-call providers are excluded because the call stipend already compensates late stays), a stipend agreement covers the roster's site and service date, and `actual_end_minute` is strictly later than the roster's `scheduled_day_end_minute`, then one `LATE_STAY` ledger entry is created for the overrun minutes multiplied by the agreement's `late_stay_rate_cents_per_minute`, and the daily-cap waterfall of §3.8 runs for that provider and date.

Cancellation moves `SCHEDULED → CANCELLED` and requires a `cancellation_reason` (enforced by the schema layer) plus a clock date on or before the roster's `service_date` — cancelling strictly after the service date is rejected with `ERR_CLOCK_DATE_MISMATCH`, and a case in any other state is rejected with `ERR_CASE_NOT_CANCELLABLE`. The system records `cancellation_notice_minutes`: when the clock date equals the service date, it is `scheduled_start_minute` minus the clock minute-of-day; when the clock is still on an earlier date, it is 1,440 plus `scheduled_start_minute` minus the clock minute-of-day. All `PROPOSED` and `CONFIRMED` assignments on the case transition to `CANCELLED`, each bumping its own `version`, and the case's `version` increments. Standby pay then applies when the `CASE_PRIMARY` assignment was `CONFIRMED` at cancel time and a stipend agreement covers the site and date: notice under 120 minutes (two hours) accrues the agreement's `standby_full_cents`; notice of at least 120 minutes but under 1,440 minutes (a full day) accrues `standby_partial_cents`; notice of 1,440 minutes or more accrues nothing and creates no entry. A notice of exactly 120 minutes therefore pays the partial tier, and exactly 1,440 minutes pays nothing. Any entry created feeds the daily-cap waterfall for that provider and date (§3.8).

### 3.7. Charge Units, Modifier Assignment, and the Claims Pipeline

Every claim's money begins as **units**. The unit count combines four ingredients: the procedure's `base_units` from its fee-schedule row; **time units**, computed as the anesthesia minutes divided by fifteen and rounded half-up to one decimal place (six minutes yields 0.4, seven minutes 0.5, two hours exactly 8.0); a physical-status adder from the ASA table — `P1`, `P2`, and `P6` add nothing, `P3` adds one unit, `P4` adds two, `P5` adds three; and two qualifying units when `emergency_flag` is true, zero otherwise. The total `units_total` is the sum of those four, rounded half-up to one decimal place. Final claims use actual minutes (`actual_end_minute` minus `actual_start_minute`); the provisional estimate of §3.3 uses scheduled minutes.

Which conversion factor and modifier applies depends on who did the work and whether direction was verified — the compliance crux of the whole billing engine. Let the *primary* be the case's `CASE_PRIMARY` assignment that reached `COMPLETED` via the completion cascade, and the *directing* assignment likewise for `CASE_DIRECTING`, which may be absent:

- An `ANESTHESIOLOGIST` primary with no directing assignment bills `PERSONAL` at 8,000 cents per unit, taking 100 percent of the charge.
- A `CRNA` or `AA` primary with no directing assignment bills `QZ` at 7,500 cents per unit, taking 100 percent.
- When a directing assignment exists and its attestation is `VERIFIED` at completion, the case bills as medical direction. The physician's claim carries `QY` if the physician's peak directed concurrency was exactly one room, or `QK` otherwise — where peak counts the physician's `CONFIRMED`-or-`COMPLETED` `CASE_DIRECTING` assignments on the same service date whose cases' scheduled half-open intervals contain this case's `scheduled_start_minute`, this case included. Both direction claims use a gross of 8,001 cents per unit, and the primary's claim carries `QX` as the split remainder below.
- When a directing assignment exists but its attestation is **not** `VERIFIED` at completion, the direction collapses: the primary's claim bills `QZ` at 7,500 cents per unit for 100 percent of its own units, and the physician's claim bills `AD` at a flat three units (no time units at all), charged as three units times 4,000 cents per unit.

For verified direction, the 50/50 split follows a pinned rounding order that implementations must reproduce exactly: first round the unit total to one decimal (per the unit math above); then multiply by 8,001 cents and round the gross half-up to whole cents; then the physician's `charge_cents` is half the gross, rounded half-up; finally the primary's `charge_cents` is the gross **minus** the physician's half — so when the gross is an odd number of cents, the physician's half is the one that rounds up and the primary receives one cent less. Rounding each half independently would double-count the odd cent and is explicitly wrong.

Claims live a billing-office lifecycle. They are born `DRAFT` — either auto-created at case completion as above, or created manually by a `BillingSpecialist` naming a `case_id` and `provider_id`; manual creation requires the case to be `COMPLETED` and the provider to hold a `COMPLETED` assignment on it, else `ERR_NO_COMPLETED_ASSIGNMENT`, and it recomputes `modifier_code`, `units_total`, and `charge_cents` identically to the completion cascade. Manual duplicates are tolerated at creation because the dedupe gate sits at the next step: marking a claim ready moves `DRAFT → READY` (or, on resubmission, `DENIED → READY`) and first checks that no *other* claim for the same `case_id` and `provider_id` already sits in `READY`, `SUBMITTED`, or `PAID` (violations are `ERR_DUPLICATE_CLAIM`) and then that `charge_cents` does not exceed the procedure's `contracted_max_cents` (violations are `ERR_CHARGE_EXCEEDS_MAX`, HTTP 402) — the referential duplicate check deliberately precedes the fiscal check. Marking from any status other than `DRAFT` or `DENIED` is `ERR_CLAIM_NOT_READYABLE`. A resubmitted claim increments `resubmission_count` by one and clears `denial_reason` to null, without recomputing its charge. Submission moves `READY → SUBMITTED` and requires the claim's case's roster to be `LOCKED` (else `ERR_ROSTER_NOT_LOCKED`); a claim not `READY` is `ERR_CLAIM_NOT_SUBMITTABLE`. From `SUBMITTED`, recording a payment moves the claim to `PAID` and stores the supplied `paid_amount_cents`; recording a denial moves it to `DENIED` and stores the supplied `denial_reason`; write-off moves it to `WRITTEN_OFF`. Settlement actions against a claim that is not `SUBMITTED` — or a write-off against a claim that is neither `SUBMITTED` nor `DENIED` — are rejected with `ERR_CLAIM_NOT_SETTLABLE`. `PAID` and `WRITTEN_OFF` are terminal; `DENIED` loops back through mark-ready. Claim lists may be filtered by `case_id`, `provider_id`, `status`, or `modifier_code`.

### 3.8. Stipend Ledger, Daily Cap Waterfall, and Monthly Subsidy Summary

The hospital-subsidy side of the books is a ledger of **stipend entries**. Each entry is system-created (never directly posted by a user) and records the `provider_id`, the `roster_id` that supplies the site and date context, an `entry_type` of `CALL`, `LATE_STAY`, or `STANDBY`, the `occurred_date` copied from the roster's `service_date`, the raw `amount_cents` accrued, and the `applied_amount_cents` actually payable after caps. Entries begin `ACCRUED`.

Capping runs as a daily waterfall per provider per `occurred_date`. The bucket contains that provider's entries for the date that are not `VOIDED` and whose type is `STANDBY` or `LATE_STAY`; `CALL` entries are exempt and always apply in full, their `applied_amount_cents` equal to `amount_cents`. The bucket is walked in `created_at` ascending order — creation timestamps at three-fractional-digit resolution make ties practically impossible, but should one ever be observed, the earlier `created_at` wins and record identifiers are never consulted as a tiebreaker — and each entry's `applied_amount_cents` is the smaller of its own `amount_cents` and the remaining capacity under a five-hundred-dollar (50,000-cent) daily ceiling after the entries before it. The walk always restarts from the beginning whenever any entry in the bucket is created or voided, which keeps the result deterministic and order-sensitive: a standby entry accrued at cancellation precedes a late-stay entry accrued at completion later that day. A `GroupAdministrator` may void an `ACCRUED` entry (voiding anything else is `ERR_ENTRY_NOT_VOIDABLE`), moving it to `VOIDED`, bumping its `version`, and re-running the waterfall so the remaining entries re-apply in order.

A month-to-date summary answers how much subsidy a provider has actually earned in a calendar month. Given a `provider_id` and a `month` in `YYYY-MM` form, the summary collects that provider's non-`VOIDED` entries whose `occurred_date` falls within the month and reports `gross_cents` (the sum of raw `amount_cents`), then applies a second-level waterfall: entries are walked in order of `occurred_date` ascending, then `created_at` ascending, and each entry contributes the smaller of its already-daily-capped `applied_amount_cents` and the remaining capacity under a four-thousand-dollar (400,000-cent) monthly ceiling. The response carries `provider_id`, `month`, `gross_cents`, `applied_cents` (the sum of monthly-allowed contributions), `capped_cents` (the difference between gross and applied), and `entry_count`. The daily cap always bites first and the monthly cap second — the monthly walk consumes daily-capped applied amounts, never raw amounts. Ledger lists may be filtered by `provider_id`, `roster_id`, `entry_type`, or `status`.

### 3.9. Compliance Audits, Findings, and Risk Scoring

The audit subsystem answers two questions at once: how much exposure is still mitigable right now, and how much actually went wrong over the period. A `ComplianceAuditor` runs a scan over a roster by supplying its `roster_id`. At most one `OPEN` audit exists per roster: if one is already open, the scan merges into it; otherwise a new `OPEN` audit is created. Merging dedupes — a candidate finding is skipped when an `OPEN` finding with the same `finding_type`, `case_id`, and `assignment_id` already exists in that audit. The scan raises three rule families:

- **Concurrency retro-breach** (`CONCURRENCY_RETRO_BREACH`, severity `CRITICAL`): for each physician, the scan builds the actual half-open intervals (`actual_start_minute` to `actual_end_minute`) of the roster's `COMPLETED` cases carrying that physician's `COMPLETED` `CASE_DIRECTING` assignment. If the peak overlap exceeds four concurrent rooms, exactly one finding is raised per physician per roster, linked to the peak-set case with the latest `actual_start_minute` — ties broken by earliest `created_at`.
- **Credential lapse** (`CREDENTIAL_LAPSE`, severity `MINOR`): each `PROPOSED` or `CONFIRMED` case assignment on the roster whose provider's earlier of `credential_expires_on` and `dea_expires_on` falls strictly before the roster's `service_date` yields one finding, linked via `assignment_id` (its `case_id` left null only for malformed imports, which never occur in normal flows).
- **TEFRA gap** (`TEFRA_GAP`, severity `MAJOR`): each `COMPLETED` case with a `COMPLETED` `CASE_DIRECTING` assignment whose attestation is not `VERIFIED` yields one finding, the same shape as the completion-time auto-finding of §3.6.

After merging, the audit's scores recompute. Every finding carries a `severity` mapped one-to-one from its `finding_type` — `CREDENTIAL_LAPSE` maps to `MINOR`, `TEFRA_GAP` to `MAJOR`, `CONCURRENCY_RETRO_BREACH` to `CRITICAL` — and the severity weights are fixed: `MINOR` findings weigh 10, `MAJOR` 30, `CRITICAL` 60. Only `OPEN` findings count. Each finding's bucket case is its own `case_id` when set, otherwise the case of its linked assignment. The `realtime_score` sums the weights of open findings whose bucket case is still non-terminal (`SCHEDULED` or `IN_PROGRESS`) — exposure that can still be mitigated. The `period_score` sums the weights of open findings whose bucket case is terminal (`COMPLETED` or `CANCELLED`) — the chronological actuals. The `risk_band` derives from `period_score`: below 20 is `LOW`; at least 20 but below 50 is `ELEVATED`; at least 50 but below 100 is `HIGH`; 100 or more is `CRITICAL` — so a period score of exactly 20 lands `ELEVATED` and exactly 100 lands `CRITICAL`. Because a finding migrates between the two scores when its case goes terminal, identical finding sets can yield different realtime and period pictures.

Findings leave the `OPEN` set through human review. A `ComplianceAuditor` resolves an `OPEN` finding, optionally recording a `resolution_note`, or dismisses it, optionally supplying a `dismissal_reason` that is likewise recorded on the finding's `resolution_note`; both actions require the parent audit to be `OPEN` (else `ERR_AUDIT_NOT_OPEN`), move the finding to `RESOLVED` or `DISMISSED`, bump its `version`, and trigger recomputation of the parent audit's `realtime_score`, `period_score`, and `risk_band`. Once every finding on an audit is `RESOLVED` or `DISMISSED`, the auditor may close the audit, moving it from `OPEN` to the terminal `CLOSED` state; any lingering `OPEN` finding rejects the close with `ERR_UNRESOLVED_FINDINGS`. Audit lists may be filtered by `roster_id` or `status`; finding lists by `audit_id`, `case_id`, `assignment_id`, `finding_type`, or `status`.

## 4. Endpoint Definitions

All endpoints are mounted under `/anesthesia-ops`. Operations that create a new resource respond with HTTP 201; all other successful operations — modifications, state transitions, reads, and the clock set — respond with HTTP 200. Error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /anesthesia-ops/_clock/set_current_utc | Set the logical clock; sweeps provider suspensions and call-window auto-completions with CALL stipend accrual | GroupAdministrator |
| POST | /anesthesia-ops/sites | Create a facility site | GroupAdministrator |
| GET | /anesthesia-ops/sites/{id} | Get a site | All roles |
| POST | /anesthesia-ops/providers | Register a provider (anesthesiologist, CRNA, or AA) | GroupAdministrator |
| GET | /anesthesia-ops/providers | List providers (filterable by type and status) | All roles |
| GET | /anesthesia-ops/providers/{id} | Get a provider | All roles |
| PATCH | /anesthesia-ops/providers/{id}/credentials | Update credential/DEA expiry dates (OCC-guarded); reinstates suspended providers when both dates are current; may raise CREDENTIAL_LAPSE findings | GroupAdministrator |
| POST | /anesthesia-ops/fee-schedules | Create a procedure-code fee row | GroupAdministrator |
| GET | /anesthesia-ops/fee-schedules/{id} | Get a fee-schedule row | All roles |
| PATCH | /anesthesia-ops/fee-schedules/{id} | Amend base units or contracted maximum | GroupAdministrator |
| POST | /anesthesia-ops/stipend-agreements | Create a hospital stipend/subsidy agreement for a site over a closed date window | GroupAdministrator |
| GET | /anesthesia-ops/stipend-agreements | List stipend agreements (filterable by site) | All roles |
| GET | /anesthesia-ops/stipend-agreements/{id} | Get a stipend agreement | All roles |
| POST | /anesthesia-ops/rosters | Create a daily roster for a site (unique per site and date) | Scheduler |
| GET | /anesthesia-ops/rosters | List rosters (filterable by site, service date, lifecycle) | All roles |
| GET | /anesthesia-ops/rosters/{id} | Get a roster, including derived posture | All roles |
| PATCH | /anesthesia-ops/rosters/{id} | Update staffing requirements (OCC-guarded); allowed in DRAFT or PUBLISHED | Scheduler |
| POST | /anesthesia-ops/rosters/{id}/publish | Publish the roster (DRAFT to PUBLISHED) | Scheduler |
| POST | /anesthesia-ops/rosters/{id}/unpublish | Revert the roster to DRAFT; blocked once any case has started or completed | Scheduler |
| POST | /anesthesia-ops/rosters/{id}/lock | Lock the roster (PUBLISHED to LOCKED); requires all cases terminal; opens billing | Scheduler |
| POST | /anesthesia-ops/cases | Schedule a case on a roster | Scheduler |
| GET | /anesthesia-ops/cases | List cases (filterable by roster, status) | All roles |
| GET | /anesthesia-ops/cases/{id} | Get a case, including provisional and final charge fields | All roles |
| PATCH | /anesthesia-ops/cases/{id} | Reschedule a SCHEDULED case (OCC-guarded); revalidates ratio, double-booking, and rest for its live assignments; recomputes the provisional charge when a primary is confirmed | Scheduler |
| POST | /anesthesia-ops/cases/{id}/start | Start a case, stamping the actual start minute from the logical clock | Scheduler |
| POST | /anesthesia-ops/cases/{id}/complete | Complete a case; fires the completion cascade (assignments close, claims auto-create, TEFRA-gap finding, late-stay stipend) | Scheduler |
| POST | /anesthesia-ops/cases/{id}/cancel | Cancel a SCHEDULED case; fires the cancellation cascade (assignments cancel, standby stipend tiering) | Scheduler |
| POST | /anesthesia-ops/cases/{id}/assignments | Propose a case assignment (OCC-guarded); supersedes any live same-role assignment | Scheduler |
| GET | /anesthesia-ops/assignments | List case assignments (filterable by case, provider, roster, status, role) | All roles |
| GET | /anesthesia-ops/assignments/{id} | Get a case assignment | All roles |
| POST | /anesthesia-ops/assignments/{id}/accept | The assigned provider accepts (PROPOSED to CONFIRMED); re-checks suspension and credential currency | AttendingAnesthesiologist, CRNA |
| POST | /anesthesia-ops/assignments/{id}/decline | The assigned provider declines (PROPOSED to DECLINED) | AttendingAnesthesiologist, CRNA |
| POST | /anesthesia-ops/assignments/{id}/cancel | Scheduler cancels a PROPOSED or CONFIRMED assignment while the case is still SCHEDULED; no stipend | Scheduler |
| POST | /anesthesia-ops/call-assignments | Schedule a call-coverage window on a roster (closed interval; per-provider per-date overlap rejected) | Scheduler |
| GET | /anesthesia-ops/call-assignments | List call assignments (filterable by roster, provider, status) | All roles |
| GET | /anesthesia-ops/call-assignments/{id} | Get a call assignment | All roles |
| POST | /anesthesia-ops/call-assignments/{id}/release | Release a provider from call early; tiered stipend by served fraction | Scheduler |
| POST | /anesthesia-ops/attestations | Create a TEFRA direction attestation for a case and physician (one per pair) | Scheduler, AttendingAnesthesiologist |
| GET | /anesthesia-ops/attestations | List attestations (filterable by case, physician, status) | All roles |
| GET | /anesthesia-ops/attestations/{id} | Get an attestation | All roles |
| POST | /anesthesia-ops/attestations/{id}/submit | The attesting physician submits all seven TEFRA steps (from IN_PROGRESS or REJECTED) | AttendingAnesthesiologist |
| POST | /anesthesia-ops/attestations/{id}/verify | A different anesthesiologist verifies the attestation (segregation of duties) | AttendingAnesthesiologist |
| POST | /anesthesia-ops/attestations/{id}/reject | A different anesthesiologist rejects the attestation, returning it for revision | AttendingAnesthesiologist |
| POST | /anesthesia-ops/claims | Manually create a DRAFT claim for a COMPLETED case and a provider with a COMPLETED assignment | BillingSpecialist |
| GET | /anesthesia-ops/claims | List claims (filterable by case, provider, status, modifier) | All roles |
| GET | /anesthesia-ops/claims/{id} | Get a claim | All roles |
| POST | /anesthesia-ops/claims/{id}/mark-ready | Move DRAFT or DENIED to READY; duplicate check precedes the contracted-maximum check | BillingSpecialist |
| POST | /anesthesia-ops/claims/{id}/submit | Move READY to SUBMITTED; requires the case's roster LOCKED | BillingSpecialist |
| POST | /anesthesia-ops/claims/{id}/record-payment | Move SUBMITTED to PAID | BillingSpecialist |
| POST | /anesthesia-ops/claims/{id}/record-denial | Move SUBMITTED to DENIED | BillingSpecialist |
| POST | /anesthesia-ops/claims/{id}/write-off | Move SUBMITTED or DENIED to WRITTEN_OFF | BillingSpecialist |
| GET | /anesthesia-ops/stipend-entries | List stipend ledger entries (filterable by provider, roster, type, status) | GroupAdministrator, Scheduler, BillingSpecialist |
| GET | /anesthesia-ops/stipend-entries/{id} | Get a stipend entry | GroupAdministrator, Scheduler, BillingSpecialist |
| GET | /anesthesia-ops/stipend-entries/summary | Month-to-date subsidy summary with the monthly-cap waterfall for a provider and month | GroupAdministrator, Scheduler, BillingSpecialist |
| POST | /anesthesia-ops/stipend-entries/{id}/void | Void an ACCRUED entry; the daily waterfall re-runs for the bucket | GroupAdministrator |
| POST | /anesthesia-ops/audits | Run a compliance scan over a roster (creates an OPEN audit or merges into the existing one with dedupe) | ComplianceAuditor |
| GET | /anesthesia-ops/audits | List audits (filterable by roster, status) | GroupAdministrator, Scheduler, BillingSpecialist, ComplianceAuditor |
| GET | /anesthesia-ops/audits/{id} | Get an audit, including realtime score, period score, and risk band | GroupAdministrator, Scheduler, BillingSpecialist, ComplianceAuditor |
| POST | /anesthesia-ops/audits/{id}/close | Close an audit; all findings must be RESOLVED or DISMISSED | ComplianceAuditor |
| GET | /anesthesia-ops/findings | List audit findings (filterable by audit, case, assignment, type, status) | GroupAdministrator, Scheduler, BillingSpecialist, ComplianceAuditor |
| GET | /anesthesia-ops/findings/{id} | Get a finding | GroupAdministrator, Scheduler, BillingSpecialist, ComplianceAuditor |
| POST | /anesthesia-ops/findings/{id}/resolve | Resolve an OPEN finding (audit must be OPEN) | ComplianceAuditor |
| POST | /anesthesia-ops/findings/{id}/dismiss | Dismiss an OPEN finding (audit must be OPEN) | ComplianceAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table enumerates identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_SELF_REVIEW_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_TIME_WINDOW | 400 |
| ERR_SITE_NOT_FOUND | 404 |
| ERR_PROVIDER_NOT_FOUND | 404 |
| ERR_ROSTER_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_CALL_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_ATTESTATION_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_FEE_SCHEDULE_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_STIPEND_ENTRY_NOT_FOUND | 404 |
| ERR_AUDIT_NOT_FOUND | 404 |
| ERR_FINDING_NOT_FOUND | 404 |
| ERR_UNKNOWN_PROCEDURE_CODE | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_ROSTER_NOT_PUBLISHED | 409 |
| ERR_ROSTER_NOT_DRAFT | 409 |
| ERR_ROSTER_NOT_LOCKED | 409 |
| ERR_ROSTER_LIFECYCLE_LOCKED | 409 |
| ERR_CASES_OUTSTANDING | 409 |
| ERR_CASE_NOT_SCHEDULED | 409 |
| ERR_CASE_NOT_IN_PROGRESS | 409 |
| ERR_CASE_NOT_CANCELLABLE | 409 |
| ERR_CLOCK_DATE_MISMATCH | 409 |
| ERR_INVALID_ACTUAL_MINUTES | 409 |
| ERR_ASSIGNMENT_NOT_PROPOSED | 409 |
| ERR_ASSIGNMENT_NOT_CANCELLABLE | 409 |
| ERR_CALL_NOT_RELEASABLE | 409 |
| ERR_ATTESTATION_NOT_SUBMITTABLE | 409 |
| ERR_ATTESTATION_NOT_SUBMITTED | 409 |
| ERR_CLAIM_NOT_READYABLE | 409 |
| ERR_CLAIM_NOT_SUBMITTABLE | 409 |
| ERR_CLAIM_NOT_SETTLABLE | 409 |
| ERR_AUDIT_NOT_OPEN | 409 |
| ERR_UNRESOLVED_FINDINGS | 409 |
| ERR_ENTRY_NOT_VOIDABLE | 409 |
| ERR_PROVIDER_SUSPENDED | 409 |
| ERR_CREDENTIAL_EXPIRED | 409 |
| ERR_SUPERVISION_RATIO_EXCEEDED | 409 |
| ERR_PROVIDER_DOUBLE_BOOKED | 409 |
| ERR_CALL_WINDOW_OVERLAP | 409 |
| ERR_INSUFFICIENT_REST | 409 |
| ERR_AGREEMENT_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE_ROSTER | 409 |
| ERR_DUPLICATE_PROVIDER_NPI | 409 |
| ERR_DUPLICATE_PROCEDURE_CODE | 409 |
| ERR_DUPLICATE_ATTESTATION | 409 |
| ERR_DUPLICATE_CLAIM | 409 |
| ERR_NO_COMPLETED_ASSIGNMENT | 409 |
| ERR_TEFRA_STEPS_INCOMPLETE | 422 |
| ERR_CHARGE_EXCEEDS_MAX | 402 |
