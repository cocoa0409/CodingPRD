# Airport Badging & SIDA Access Control API — Product Requirements Document

## 1. Introduction

Airport operators live under an unforgiving regulatory regime: every person who walks beyond the public terminal into the sterile concourse, the air operations area, or the Security Identification Display Area must carry a credential backed by a fingerprint-based criminal history records check, a TSA security threat assessment, and current safety training. The badging office that administers this program juggles sponsoring employers, applicant pipelines, expiring coursework, lost and stolen credentials, escort privileges, and an annual audit whose badge-recovery rate determines whether the airport keeps its certification. Paper files and spreadsheets no longer survive that scrutiny.

This document specifies the Airport Badging & SIDA Access Control API, the system of record for that badging office. The API covers sponsor administration, applicant registration, the badge application pipeline from submission through background adjudication to issuance, training-currency tracking, badge suspension and replacement, escort privilege management, door access decisions for the physical access control system, violation adjudication with point-driven suspensions, and annual audit cycles with recovery-rate reporting. All endpoints are mounted under `/badging`. Because compliance evidence must be reconstructible for any instant, the server runs on a controllable logical clock rather than wall-clock time, and every time-driven transition — application expiry, badge expiry, training-currency regression — is a deterministic function of that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify its operational capacity. The system recognizes five distinct roles: `SponsorSignatory`, `BadgingOfficer`, `SecurityManager`, `Auditor`, and `AccessControlSystem`. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Once the headers are accepted, the caller's role must appear among the roles authorized for the target endpoint; a call outside the caller's designated role is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `SponsorSignatory`, `X-User-ID` is the `id` of the acting `Sponsor`; ownership checks on any resource that references a `Sponsor` compare the resource's foreign-key field to `X-User-ID`. A signatory may register applicants only for its own sponsor, open and withdraw applications only for its own applicants, and report lost or stolen badges only for badges its own sponsor sponsors; any mismatch is rejected with `ERR_SPONSOR_OWNERSHIP_MISMATCH`.
- When `X-User-Role` is `BadgingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `recorded_by` on a `Violation`) but does not compare it to any entity's `id`.
- When `X-User-Role` is `SecurityManager`, `X-User-ID` is likewise an opaque operator identifier. The server records it where the workflow demands accountability — as `suspended_by` on a `Badge`, as `granted_by` on an `EscortPrivilege`, or as `sustained_by` / `dismissed_by` on a `Violation` — and those recorded values later drive the segregation-of-duties checks described in §2.9, but it is never compared to an entity's `id` for ownership.
- When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `AccessControlSystem`, `X-User-ID` is an opaque identifier for the physical access control installation presenting badges at doors; it is recorded nowhere and compared to nothing.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — Sponsors, Applicants, Badge Applications, Badges, Escort Privileges, Violations, and Audit Cycles — carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T09:15:30.123Z`) recording when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every modification of the resource's properties.
- **`version` (integer):** A system-managed integer that increments by one with every modification to the resource, including modifications performed by cascading side effects originating from another resource.

Two resources deviate from this convention. A `TrainingCompletion` is an immutable record created once and never updated or deleted, and an `AccessEvent` is an append-only log row; both carry only `id` and `created_at` — the `updated_at` and `version` fields are absent from both.

### 2.5. The Logical Clock

Every timestamp the server assigns — `submitted_at`, `issued_at`, `occurred_at`, `deactivated_at`, `suspended_at`, `returned_at`, and the boundaries of computed expiry fields — is read from a single logical clock, never from the host's wall clock. At server startup the logical clock is exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time at any point afterward.

An administrative clock-setting capability, available to the `BadgingOfficer`, `SecurityManager`, and `Auditor` roles, advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Setting the clock is not a passive readjustment: in a single atomic step it sweeps every time-driven transition in the system. Badges in `ACTIVE` or `SUSPENDED` whose `expires_at` has been reached or passed transition to `EXPIRED`; non-terminal badge applications whose `application_expires_at` has been reached or passed transition to `EXPIRED`; applications resting in `READY` whose required training is no longer current regress to `PENDING_REQUIREMENTS`; and applications in `PENDING_REQUIREMENTS` whose training has become current are promoted to `READY`. Sponsor badge counts are recomputed as part of the same step, so a client observing the system immediately after a clock set sees a fully reconciled state.

### 2.6. Validation Order and Request Processing

When several rules could reject the same request, the server evaluates validations in a fixed priority order, and the first failing rule determines the error returned. The order is:

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers must both be present and non-empty; otherwise the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The caller's role must be one of the endpoint's allowed roles; otherwise `ERR_FORBIDDEN_ROLE`.
3. **Sponsor ownership.** For `SponsorSignatory` callers, the caller's `X-User-ID` must equal the sponsor that owns the target resource; otherwise `ERR_SPONSOR_OWNERSHIP_MISMATCH`.
4. **Existence and request shape.** Path identifiers are validated left to right and body references must exist — each unknown resource yields its specific not-found error (`ERR_SPONSOR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`, `ERR_ESCORT_PRIVILEGE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or `ERR_AUDIT_CYCLE_NOT_FOUND`) — while missing required fields, unknown enum values, malformed datetimes, an `escortee_count` that is negative, a `max_escortees` outside the permitted range, or an audit window whose end is not after its start are rejected here as `ERR_INVALID_REQUEST`.
5. **State preconditions.** The target entity must be in the state the transition requires, failing with the corresponding state error such as `ERR_SPONSOR_NOT_ACTIVE`, `ERR_APPLICATION_NOT_OPEN`, `ERR_APPLICATION_NOT_READY`, `ERR_BADGE_NOT_ACTIVE`, `ERR_BADGE_NOT_SUSPENDED`, `ERR_BADGE_NOT_INACTIVE`, `ERR_BADGE_NOT_REPLACEABLE`, `ERR_AUDIT_NOT_OPEN`, `ERR_ESCORT_NOT_GRANTED`, or `ERR_VIOLATION_NOT_OPEN`.
6. **Optimistic concurrency.** On the one endpoint that takes an expected-version field, the supplied version must match the resource's current `version`; otherwise `ERR_STALE_VERSION` (see §2.11).
7. **Uniqueness and segregation.** One-open-application, active-badge overlap, badge-number uniqueness, and segregation-of-duties rules, failing with `ERR_OPEN_APPLICATION_EXISTS`, `ERR_ACTIVE_BADGE_EXISTS`, `ERR_BADGE_NUMBER_TAKEN`, or `ERR_SEGREGATION_OF_DUTIES`.
8. **Temporal rules.** Suspension-served and audit-window rules, failing with `ERR_SUSPENSION_NOT_SERVED`, `ERR_AUDIT_WINDOW_OVERLAP`, or `ERR_AUDIT_WINDOW_GAP`; for audit windows the overlap check runs before the gap check.
9. **Sponsor delinquency.** Issuance is blocked while the sponsor has an overdue unreturned badge, failing with `ERR_SPONSOR_DELINQUENT`.
10. **Sponsor quota.** Issuance is blocked at the sponsor's badge quota, failing with `ERR_SPONSOR_QUOTA_EXCEEDED`.

Because of this ordering, the badge-issuance step rejects an application that is not `READY` with `ERR_APPLICATION_NOT_READY` before it ever considers whether the applicant already holds a conflicting badge, and it reports a delinquent sponsor with `ERR_SPONSOR_DELINQUENT` before it reports an exhausted quota with `ERR_SPONSOR_QUOTA_EXCEEDED`.

### 2.7. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for requests whose path contains multiple resource identifiers (for example, a sponsor's applicants or a badge's access events). The existence of each identifier is validated in sequential, left-to-right order, and the request is rejected immediately with the not-found error corresponding to the first identifier that does not resolve. A request for the escort privileges of a badge that does not exist therefore fails with `ERR_BADGE_NOT_FOUND` before any privilege data is considered, and a request under a non-existent applicant fails with `ERR_APPLICANT_NOT_FOUND` even if the remainder of the path is equally invalid.

### 2.8. Sponsor Standing: Quotas and Delinquency

Two cross-cutting measures of sponsor health gate the issuance of new credentials.

Every sponsor carries an `active_badge_quota`, supplied at registration and constrained to be at least 1, which caps the number of badges the sponsor may have in circulation. Circulation is measured by the read-only, server-computed `active_badge_count`: the number of the sponsor's badges currently in `ACTIVE` or `SUSPENDED` status. The count is recomputed whenever a badge enters or leaves those two statuses — it rises by one at issuance, falls by one when a badge is deactivated, and is unchanged by a replacement, which deactivates one badge and issues another in the same step.

Delinquency is the second measure. A sponsor is delinquent when any of its badges sits in `LOST`, `STOLEN`, `EXPIRED`, or `REVOKED` status with a `return_deadline` at or before the current logical clock — the overdue comparison is inclusive, so a badge whose return deadline is exactly now already counts against the sponsor. Issuance is refused while the sponsor is delinquent; replacement is not subject to either the quota or the delinquency check, since it conserves the sponsor's badge count and administratively accounts for the old badge.

### 2.9. Segregation of Duties

No operator may single-handedly reverse their own enforcement action. Reinstating a suspended badge requires the calling `SecurityManager` to be a different person than the manager recorded in the badge's `suspended_by` field. Dismissing a violation obeys the same principle from the other side: dismissing a violation still in `RECORDED` status requires the caller to differ from the officer in `recorded_by`, while dismissing a violation already in `SUSTAINED` status requires the caller to differ from the manager in `sustained_by`. Either conflict is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Precision, Rounding, and Calendar Arithmetic

Percentage rates in audit reporting are carried to exactly 2 decimal places using the round-half-up method. Violation points are integers, and point thresholds are evaluated as integer comparisons. All datetime comparisons — expiry checks, return-deadline checks, suspension-served checks — are made at second precision. Durations expressed in months use calendar-month addition that preserves the day of month: twelve months after a completion on 15 March lands on the following 15 March, and the badge validity cap of 24 months behaves the same way.

### 2.11. Optimistic Concurrency Control

Exactly one operation in the API is guarded by optimistic concurrency control: granting an escort privilege to a badge. The request must carry `expected_badge_version`, an integer equal to the badge's `version` as last observed by the client. If another writer has advanced the badge's version since that observation — for any reason, including a prior grant that superseded a privilege the client never saw — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check is evaluated after the state validations, so a grant against a non-`ACTIVE` badge fails with `ERR_BADGE_NOT_ACTIVE` even when the supplied version is also wrong. No other endpoint takes a version field; every other write is processed without an expected-version input.

## 3. Business Logic & Workflows

### 3.1. Sponsors and Applicant Onboarding

Everything in the badging office begins with a sponsoring employer or tenant organization. A `SecurityManager` registers a sponsor by supplying its legal `name`, a globally unique `sponsor_code`, and the `active_badge_quota` that caps how many credentials the organization may hold in circulation; the new sponsor starts in `ACTIVE` status with an `active_badge_count` of zero and a null `suspended_at`. Attempting to register a sponsor whose `sponsor_code` is already in use is a uniqueness violation, and a quota below 1 is rejected as `ERR_INVALID_REQUEST`.

With a sponsor on file, the sponsor's own `SponsorSignatory` registers the people who need credentials. Each applicant record carries a `sponsor_id` (which must equal the signatory's `X-User-ID`), the person's `full_name`, their `date_of_birth` as an ISO 8601 calendar date in year-month-day form, and the `government_id_number` that will anchor the fingerprint-based criminal history records check. Registration is refused with `ERR_SPONSOR_NOT_ACTIVE` when the sponsor has been suspended. The roster of a sponsor's applicants is available as a paginated listing to every role.

An applicant without an open badge application can be sponsored for a credential at any time. Opening an application requires only the `applicant_id` and the requested `badge_class` — one of `SIDA`, `STERILE`, or `AOA` — and copies the applicant's `sponsor_id` onto the application at creation so the record remains attributable even if the applicant data later changes. The new application enters `SUBMITTED` status with `submitted_at` set to the current logical clock and `application_expires_at` set ninety days later; an application that has not reached a terminal state by that deadline is swept to `EXPIRED` the next time the clock is set, with the boundary inclusive. An applicant may hold at most one non-terminal application — one in `SUBMITTED`, `STA_PENDING`, `PENDING_REQUIREMENTS`, or `READY` — and a second attempt is rejected with `ERR_OPEN_APPLICATION_EXISTS`. The full collection of applications can be listed with optional `applicant_id`, `sponsor_id`, and `status` filters. Until the corresponding adjudication steps occur, the application's `chrc_outcome`, `sta_outcome`, and `denial_reason` remain null, and `issued_badge_id` stays null until a badge is actually issued.

### 3.2. Background Adjudication and the Readiness Cycle

Once an application is `SUBMITTED`, a `BadgingOfficer` records the fingerprint submission and the adjudicated outcome of the criminal history records check in a single step, supplying `fingerprint_submitted_at` and an `outcome`. This step requires the application to be `SUBMITTED`; any other state fails with `ERR_APPLICATION_NOT_OPEN`. A `PASS` outcome stamps `chrc_outcome` accordingly and moves the application to `STA_PENDING` — the security threat assessment is submitted to the TSA as part of the same record, with no separate submission step. A `FAIL` outcome instead stamps `chrc_outcome` as `FAIL`, sets `denial_reason` to `CHRC_FAILED`, and terminates the application in `DENIED`.

When the TSA returns the threat assessment, the officer records its `outcome` against an application that must be `STA_PENDING`. A `CLEARED` result stamps `sta_outcome` and moves the application to `PENDING_REQUIREMENTS` — but only as a waypoint: readiness evaluation runs immediately, and if every required course for the application's `badge_class` is strictly current at the current logical clock, the application continues straight through to `READY` rather than resting at the waypoint. A `DENIED` result stamps `sta_outcome` as `DENIED`, sets `denial_reason` to `STA_DENIED`, and terminates the application in `DENIED`.

Readiness is a continuing obligation, not a one-time gate. The evaluation runs on three occasions: whenever a training completion is recorded for the applicant, whenever a threat assessment is cleared, and on every clock set. An application in `PENDING_REQUIREMENTS` is promoted to `READY` the moment every required course holds a strictly current completion; an application already in `READY` regresses to `PENDING_REQUIREMENTS` the moment some required course no longer holds one. This promotion-and-regression pair forms the `PENDING_REQUIREMENTS` ↔ `READY` cycle, and an applicant whose coursework lapses the night before issuance will find their application back at the waypoint after the next clock set.

A sponsor that loses interest in an application may withdraw it. Withdrawal by the owning `SponsorSignatory` moves any non-terminal application — `SUBMITTED`, `STA_PENDING`, `PENDING_REQUIREMENTS`, or `READY` — to `WITHDRAWN`; a terminal application rejects the attempt with `ERR_APPLICATION_NOT_OPEN`, and a signatory acting on another sponsor's application is refused with `ERR_SPONSOR_OWNERSHIP_MISMATCH`.

### 3.3. Training Courses and Currency Windows

Coursework is tracked as immutable `TrainingCompletion` records. A `BadgingOfficer` records a completion with the `applicant_id`, the `course_code`, and the `completed_at` datetime; the server computes `expires_at` by adding the course's validity period to `completed_at` using calendar-month addition that preserves the day of month. Four courses exist with four validity periods: `SIDA_INITIAL` is valid for twelve months, `AOA_SAFETY` for twenty-four months, `AOA_DRIVING` for twelve months, and `STERILE_INITIAL` for twelve months. An applicant's completion history is available as a paginated listing ordered by creation.

The courses an applicant needs depend on the credential sought. A `SIDA` badge requires `SIDA_INITIAL` and `AOA_SAFETY`. A `STERILE` badge requires `STERILE_INITIAL` alone. An `AOA` badge requires `SIDA_INITIAL` and `AOA_DRIVING`.

Currency is evaluated under two regimes, and the difference matters. A completion is **strictly current** at a given instant when its `expires_at` lies strictly in the future — a completion expiring exactly now has already lapsed. A completion is **grace-current** when its `expires_at` plus thirty days lies strictly in the future, so coursework lapsed by at most thirty days still counts. Initial issuance uses the strict regime: readiness evaluation, and therefore the `READY` gate on issuance, demands a strictly current completion for every required course. Badge replacement uses the grace regime: every required course must hold a grace-current completion, which means identical training data can pass the replacement gate while failing the readiness gate. All currency comparisons are made at second precision.

### 3.4. Badge Issuance and the Expiry Horizon

Issuance is the reward at the end of the pipeline, and the most heavily guarded operation in the office. A `BadgingOfficer` issues the credential for a `READY` application by presenting a `badge_number`, which must be globally unique across all badges ever printed — a reused number is refused with `ERR_BADGE_NUMBER_TAKEN`. Four further gates stand between the request and the credential, evaluated in the system's fixed validation order. The application itself must be `READY`, else `ERR_APPLICATION_NOT_READY`. The applicant must not already hold another badge of the same `badge_class` in `ACTIVE`, `SUSPENDED`, `LOST`, or `STOLEN` status whose validity window — the half-open interval from its `issued_at` up to but not including its `expires_at` — covers the issuance instant, else `ERR_ACTIVE_BADGE_EXISTS`; because the interval is half-open, an old badge expiring exactly at the issuance instant does not conflict. The sponsor must not be delinquent on unreturned badges, else `ERR_SPONSOR_DELINQUENT`. And the sponsor's `active_badge_count` must be below its `active_badge_quota`, else `ERR_SPONSOR_QUOTA_EXCEEDED` — a sponsor sitting exactly at its quota is blocked, while one badge of headroom is enough to proceed.

A successful issuance creates the `Badge` in `ACTIVE` status, copying the `applicant_id`, `sponsor_id`, and `badge_class` from the application, recording `issued_at` from the logical clock, and stamping the application's `issued_badge_id` with the new badge's `id` as the application itself moves to the terminal `ISSUED` state. The sponsor's `active_badge_count` rises by one.

The new badge's `expires_at` is computed as the earlier of two horizons: twenty-four calendar months after `issued_at`, or the nearest expiry among the completions satisfying the required courses. Under the initial-issuance variant each course's horizon is simply the completion's `expires_at`, so a badge issued against coursework that lapses in five months carries a five-month validity regardless of the two-year cap. The computation combines at least three inputs — the issuance instant, the twenty-four-month cap, and one horizon per required course — through nested earliest-of comparisons.

### 3.5. Suspension, Deactivation, Return, and Replacement

Badges leave circulation through several doors, and each door leaves different paperwork. While a badge remains in `ACTIVE` status, its `deactivated_at`, `return_deadline`, `returned_at`, `suspended_by`, `suspended_until`, `suspension_reason`, and `superseded_by_badge_id` are all null; each is stamped only when the corresponding lifecycle event occurs.

A `SecurityManager` may suspend an `ACTIVE` badge at any time, optionally noting a `reason`; the badge moves to `SUSPENDED` with `suspension_reason` set to `MANUAL`, `suspended_by` recording the acting manager, and `suspended_until` left null, marking it immediately reinstatable. The same transition fires automatically, with `suspension_reason` set to `VIOLATION_POINTS` and a computed `suspended_until`, when sustained violation points cross the threshold described in §3.8. Any suspension — manual, points-driven, or the sponsor cascade of §3.7's neighbor workflow — immediately revokes the badge's `GRANTED` escort privilege with `revoked_reason` set to `BADGE_SUSPENDED`.

Reinstatement returns a `SUSPENDED` badge to `ACTIVE`, clearing `suspended_by`, `suspended_until`, and `suspension_reason` to null. Two conditions protect the action: the caller must differ from the manager who suspended the badge (`ERR_SEGREGATION_OF_DUTIES`), and when `suspended_until` is set the current logical clock must have reached or passed it, else `ERR_SUSPENSION_NOT_SERVED` — a condition that can only bite on points-driven suspensions, since manual and sponsor suspensions carry a null `suspended_until`. Reinstatement never restores the escort privilege; regaining escort rights requires a fresh grant.

When a badge goes missing, the owning sponsor's signatory or a `BadgingOfficer` reports it with a `report_type` of `LOST` or `STOLEN`, moving an `ACTIVE` or `SUSPENDED` badge to the matching status. Either way the badge's `deactivated_at` is set to the current clock and its `return_deadline` to thirty days later, its `GRANTED` escort privilege is revoked with `revoked_reason` `BADGE_DEACTIVATED`, and the sponsor's `active_badge_count` falls by one. A `SecurityManager` may also permanently revoke an `ACTIVE` or `SUSPENDED` badge, optionally recording a `reason`; revocation produces the same deactivation bookkeeping — `deactivated_at` now, `return_deadline` thirty days out, escort privilege revoked as `BADGE_DEACTIVATED`, sponsor count recomputed — but lands the badge in `REVOKED`. Badges that age out under the clock sweep land in `EXPIRED` with `deactivated_at` set to the badge's own `expires_at` and `return_deadline` thirty days after that, again revoking any granted escort privilege as `BADGE_DEACTIVATED`.

Physical recovery closes the loop. A `BadgingOfficer` marks a badge in `LOST`, `STOLEN`, `EXPIRED`, or `REVOKED` as returned; the badge moves to `RETURNED` with `returned_at` stamped from the clock. Any other status is refused with `ERR_BADGE_NOT_INACTIVE`.

Replacement is the renewal path and the only operation that mints a credential without consuming quota. A `BadgingOfficer` may replace a badge in `ACTIVE`, `SUSPENDED`, or `EXPIRED` status by presenting a fresh `badge_number`. Three conditions guard the operation, all reported as `ERR_BADGE_NOT_REPLACEABLE`: the badge must be in one of those three statuses; every required course for its `badge_class` must hold a completion current under the renewal-grace regime — `expires_at` plus thirty days still in the future; and the computed expiry of the replacement must lie in the future. On success the old badge becomes `VOIDED` with `deactivated_at` set to now, `return_deadline` left null because a voided badge is administratively accounted and carries no return obligation, and `superseded_by_badge_id` pointing at its replacement; its `GRANTED` escort privilege, if any, is revoked with `revoked_reason` `SUPERSEDED`. The new badge is created in `ACTIVE` status under the same applicant, sponsor, and class, with `issued_at` set to now and `expires_at` computed under the renewal variant of the expiry rule — each required course's horizon is its completion's `expires_at` plus thirty days, and the badge expires at the earlier of twenty-four months after issuance or the nearest such horizon. The sponsor's `active_badge_count` is unchanged: one deactivation offsets one issuance. The badge collection can be listed with optional `applicant_id`, `sponsor_id`, `application_id`, `superseded_by_badge_id`, and `status` filters, which makes the replacement chain directly queryable.

### 3.6. Escort Privileges and Supersession

Certain badge holders may shepherd unbadged visitors through controlled doors. That authority is modeled as an `EscortPrivilege` attached to a badge, carrying a `max_escortees` limit — an integer no lower than 1 and no higher than 10, with out-of-range values rejected as `ERR_INVALID_REQUEST` — plus the `granted_by` identity of the acting `SecurityManager`, a `status` of `GRANTED` or `REVOKED`, and a `revoked_reason` that stays null while the privilege is live.

Granting is the API's one optimistic-concurrency-guarded write: the request carries `max_escortees` and `expected_badge_version`, and the badge must be `ACTIVE` with a current `version` equal to the supplied expectation, else the grant fails as described in §2.11. A badge holds at most one live privilege, so a successful grant supersedes any currently `GRANTED` privilege on the same badge, retiring it to `REVOKED` with `revoked_reason` `SUPERSEDED`; the grant also increments the badge's `version` by one, which is precisely the advance a stale client would fail to match. A `SecurityManager` may also revoke a live privilege outright, moving it from `GRANTED` to `REVOKED` with `revoked_reason` `MANUAL`; acting on a privilege that is not `GRANTED` is refused with `ERR_ESCORT_NOT_GRANTED`. The remaining two revocation causes arrive as cascades from the badge: `BADGE_SUSPENDED` when the badge is suspended, and `BADGE_DEACTIVATED` when it leaves circulation. The full history of a badge's privileges, current and retired, is available as a paginated listing.

### 3.7. Door Access Decisions and the Zone Catalogue

The `AccessControlSystem` role presents credentials at doors, and every presentation is evaluated against a fixed four-zone catalogue and permanently logged. `PUBLIC_TERMINAL` admits no badge class on its own authority but permits escorted entry. `STERILE_CONCOURSE` admits `SIDA` and `STERILE` badges and permits escorted entry. `AOA_MOVEMENT` admits `SIDA` and `AOA` badges and permits escorted entry. `SECURE_ID_AREA` admits only `SIDA` badges and forbids escorted entry entirely.

Each access check supplies a `zone_code`, an optional `badge_id` — null for a badgeless attempt — and an optional `escortee_count` defaulting to zero, and produces an `AccessEvent` row recording the `decision`, the `denial_reason` when refused, and `occurred_at` from the logical clock. A denial is a logged business outcome, not a fault: the check returns 201 Created with `decision` set to `DENIED` and the appropriate reason, never an error response. The evaluation walks a fixed sequence. A null `badge_id` is denied with `DENIED_NO_BADGE`. A badge not in `ACTIVE` status is denied with `DENIED_BADGE_INACTIVE`. A badge whose `badge_class` is outside the zone's admitted set is denied with `DENIED_ZONE_CLASS`. When the `escortee_count` is positive, three further tests apply in order: a zone that forbids escorted entry denies with `DENIED_ESCORT_NOT_PERMITTED`; a badge with no `GRANTED` escort privilege denies with `DENIED_ESCORT_NOT_PERMITTED`; and a party larger than the privilege's `max_escortees` denies with `DENIED_ESCORT_CAPACITY` — the boundary is inclusive, so a party exactly equal to `max_escortees` is admitted. A presentation surviving every test is logged with `decision` `ALLOWED` and a null `denial_reason`. A badge's event history is available as a paginated listing.

### 3.8. Violations, Points, and Threshold Cascades

Enforcement begins when a `BadgingOfficer` records a `Violation` against a badge, supplying the `badge_id`, the `violation_type`, and the `occurred_at` instant. The server assigns `points` from the type — `FAILURE_TO_DISPLAY` is worth 3 points, `ESCORT_VIOLATION` 6 points, `UNAUTHORIZED_AREA` 6 points, and `SECURITY_BREACH` 12 points — stamps `recorded_by` with the acting officer, and opens the record in `RECORDED` status.

Adjudication belongs to the `SecurityManager`. Sustaining a `RECORDED` violation moves it to `SUSTAINED`, stamps `sustained_by`, and immediately recomputes the holder's windowed points: the sum of points across all `SUSTAINED` violations attached to badges of the same applicant whose `occurred_at` falls strictly within the trailing twenty-four months — a violation exactly twenty-four months old is excluded. The recomputed total drives a threshold cascade against the badge the violation was recorded on. At 24 points or more, an `ACTIVE` or `SUSPENDED` badge is revoked outright, following the same deactivation bookkeeping and escort-revocation chain as a manual revocation. Otherwise, at 12 points or more, an `ACTIVE` badge is suspended under the `VIOLATION_POINTS` reason with `suspended_by` set to the sustaining manager and `suspended_until` tiered by severity: a total from 12 through 17 points suspends for seven days, while a total from 18 through 23 points suspends for thirty days. Exactly 12 points suspends; 11 points leaves the badge untouched. A violation in any other state refuses the sustain with `ERR_VIOLATION_NOT_OPEN`.

Dismissal unwinds the accounting without unwinding the consequences. A `SecurityManager` may dismiss a violation in `RECORDED` or `SUSTAINED` status, subject to the segregation-of-duties rule of §2.9; the record moves to `DISMISSED` with `dismissed_by` stamped, and the holder's windowed points are recomputed with the dismissed violation's points removed. A badge already suspended or revoked by the threshold cascade is not automatically restored — reinstatement is a separate manual action with its own guards. A badge's violation history is available as a paginated listing.

### 3.9. Sponsor Suspension and the Annual Audit

The heaviest hammer in the system is sponsor suspension. When a `SecurityManager` suspends an `ACTIVE` sponsor — optionally recording a `reason` — the sponsor moves to `SUSPENDED` with `suspended_at` stamped, and three cascades fire in one step. Every non-terminal application of that sponsor collapses to `DENIED` with `denial_reason` `SPONSOR_SUSPENDED`. Every badge of that sponsor in `ACTIVE` status moves to `SUSPENDED` with `suspension_reason` `SPONSOR_SUSPENDED`, `suspended_by` set to the acting manager, and `suspended_until` null; badges already `SUSPENDED` keep their original `suspended_by`, `suspended_until`, and `suspension_reason` untouched. And each badge that newly entered `SUSPENDED` revokes its `GRANTED` escort privilege with `revoked_reason` `BADGE_SUSPENDED`. Sponsor suspension is the third and final source of the suspension cascade, after manual action and violation points. Acting on a sponsor that is not `ACTIVE` is refused with `ERR_SPONSOR_NOT_ACTIVE`.

Accountability over the whole badge population lands once a year in an audit cycle. An `Auditor` opens a cycle by supplying a `window_start` and a `window_end` — the window is the half-open interval from `window_start` up to but not including `window_end`, the end must be strictly after the start (else `ERR_INVALID_REQUEST`), and the new window must not overlap any existing cycle's window, else `ERR_AUDIT_WINDOW_OVERLAP`. Touching windows are permitted, and more than permitted: once any cycle exists, a new cycle's `window_start` must fall exactly on the latest cycle's `window_end`, so cycles tile contiguously with no gaps; a start later than that boundary is rejected with `ERR_AUDIT_WINDOW_GAP`, and the overlap check is evaluated before the gap check. A fresh cycle opens in `OPEN` status with all close-computed fields null.

While a cycle is `OPEN`, reading it returns live provisional figures computed against the current logical clock. The provisional scope restricts the audit's badges to those whose `return_deadline` has been set and has already passed: `due_scoped_count` counts them, `due_accounted_count` counts how many of them now stand in `RETURNED` or `VOIDED` status, and `recovery_rate_provisional_pct` is the accounted share of the due scope expressed as a percentage, rounded half-up to two decimals — or null when nothing is due yet.

Closing the cycle, an `Auditor`-only action requiring the cycle to be `OPEN` (else `ERR_AUDIT_NOT_OPEN`), moves the cycle to its terminal `CLOSED` status and freezes the final figures. The frozen `scoped_count` counts every badge whose `deactivated_at` falls within the window; the frozen `accounted_count` counts how many of those stand in `RETURNED` or `VOIDED` — note that a voided badge is accounted without ever being returned, which is exactly why replacement carries no return obligation. The `recovery_rate_pct` is the accounted share of the full scope rounded half-up to two decimals, or 100.00 when the scope is empty. The `per_class_rates` array carries one entry per badge class present in the scope, each entry giving that class's `badge_class`, `scoped`, `accounted`, and `rate_pct` rounded half-up to two decimals, sorted alphabetically by class — `AOA`, then `SIDA`, then `STERILE`. The rounding order is pinned: the overall rate is aggregated over the full scope and then rounded, never computed as the mean of the rounded per-class rates, so the same scope data can yield an overall figure that no averaging of the per-class figures reproduces. The `outcome` is `COMPLIANT` when the frozen rate is at least 95.00 and `DEFICIENT` below that line. At close the provisional fields — `due_scoped_count`, `due_accounted_count`, and `recovery_rate_provisional_pct` — become null and stay null. Because the provisional denominator counts only badges past their thirty-day return deadline while the final denominator counts the entire deactivation scope, the two rates diverge whenever not-yet-due unreturned badges exist.

## 4. Endpoint Definitions

Operations that create new resources — registering a sponsor, applicant, application, training completion, violation, or audit cycle, issuing or replacing a badge, granting an escort privilege, or logging an access check — return a `201 Created` status code. Operations that modify an existing resource in place, including all state transitions and the clock set, return a `200 OK` status code. Readers must consult §2 and §3 for each operation's request payload, validations, and side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/badging/sponsors` | Register a sponsoring employer/tenant organization | SecurityManager |
| GET | `/badging/sponsors/{id}` | Get a sponsor (includes computed `active_badge_count`) | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/sponsors/{id}/suspend` | Suspend a sponsor; cascades to its applications and badges | SecurityManager |
| POST | `/badging/applicants` | Register an applicant under the caller's sponsor | SponsorSignatory |
| GET | `/badging/applicants/{id}` | Get an applicant | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| GET | `/badging/sponsors/{id}/applicants` | List applicants of a sponsor | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/applications` | Open a badge application for an applicant of the caller's sponsor | SponsorSignatory |
| GET | `/badging/applications` | List applications, filterable by applicant, sponsor, and status | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| GET | `/badging/applications/{id}` | Get an application | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/applications/{id}/record-chrc` | Record fingerprint + CHRC submission and its adjudicated result in one step | BadgingOfficer |
| POST | `/badging/applications/{id}/record-sta-result` | Record the TSA security threat assessment result | BadgingOfficer |
| POST | `/badging/applications/{id}/withdraw` | Sponsor withdraws a non-terminal application | SponsorSignatory |
| POST | `/badging/applications/{id}/issue-badge` | Issue the badge for a READY application | BadgingOfficer |
| POST | `/badging/training-completions` | Record a completed training course for an applicant | BadgingOfficer |
| GET | `/badging/applicants/{id}/training-completions` | List an applicant's training completions | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| GET | `/badging/badges` | List badges, filterable by applicant, sponsor, application, supersession link, and status | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| GET | `/badging/badges/{id}` | Get a badge | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/badges/{id}/suspend` | Manually suspend an ACTIVE badge | SecurityManager |
| POST | `/badging/badges/{id}/reinstate` | Reinstate a SUSPENDED badge under segregation of duties | SecurityManager |
| POST | `/badging/badges/{id}/report-lost` | Report a badge lost or stolen | SponsorSignatory, BadgingOfficer |
| POST | `/badging/badges/{id}/mark-returned` | Record physical return of a deactivated badge | BadgingOfficer |
| POST | `/badging/badges/{id}/revoke` | Permanently revoke a badge | SecurityManager |
| POST | `/badging/badges/{id}/replace` | Replace a badge; old becomes VOIDED, new issued under the renewal-grace variant | BadgingOfficer |
| POST | `/badging/badges/{id}/escort-privileges` | Grant (or supersede) the badge's escort privilege; OCC-guarded | SecurityManager |
| GET | `/badging/badges/{id}/escort-privileges` | List escort privileges of a badge, current and historical | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/escort-privileges/{id}/revoke` | Manually revoke a GRANTED escort privilege | SecurityManager |
| POST | `/badging/access-checks` | Evaluate a door/zone access attempt and log it; denial is a logged decision, not an error | AccessControlSystem |
| GET | `/badging/badges/{id}/access-events` | List access events for a badge | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/violations` | Record a violation against a badge | BadgingOfficer |
| GET | `/badging/badges/{id}/violations` | List violations for a badge | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/violations/{id}/sustain` | Sustain a recorded violation; may suspend or revoke the badge by points threshold | SecurityManager |
| POST | `/badging/violations/{id}/dismiss` | Dismiss a violation under segregation of duties | SecurityManager |
| POST | `/badging/audit-cycles` | Open an annual audit cycle with a contiguous, non-overlapping window | Auditor |
| GET | `/badging/audit-cycles/{id}` | Get an audit cycle; while OPEN includes live provisional recovery fields | SponsorSignatory, BadgingOfficer, SecurityManager, Auditor, AccessControlSystem |
| POST | `/badging/audit-cycles/{id}/close` | Close the audit, freezing scope, recovery rate, per-class rates, and outcome | Auditor |
| POST | `/badging/_clock/set_current_utc` | Set the logical clock and atomically sweep all time-driven transitions | BadgingOfficer, SecurityManager, Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SPONSOR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SPONSOR_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_BADGE_NOT_FOUND` | 404 Not Found |
| `ERR_ESCORT_PRIVILEGE_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_APPLICATION_NOT_OPEN` | 409 Conflict |
| `ERR_APPLICATION_NOT_READY` | 409 Conflict |
| `ERR_BADGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_BADGE_NOT_SUSPENDED` | 409 Conflict |
| `ERR_BADGE_NOT_INACTIVE` | 409 Conflict |
| `ERR_BADGE_NOT_REPLACEABLE` | 409 Conflict |
| `ERR_AUDIT_NOT_OPEN` | 409 Conflict |
| `ERR_ESCORT_NOT_GRANTED` | 409 Conflict |
| `ERR_VIOLATION_NOT_OPEN` | 409 Conflict |
| `ERR_OPEN_APPLICATION_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_BADGE_EXISTS` | 409 Conflict |
| `ERR_BADGE_NUMBER_TAKEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SUSPENSION_NOT_SERVED` | 409 Conflict |
| `ERR_SPONSOR_DELINQUENT` | 409 Conflict |
| `ERR_SPONSOR_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_WINDOW_GAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
