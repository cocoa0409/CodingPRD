# Immigrant Welcome Center API — Product Requirements Document

## 1. Introduction

A municipal Immigrant Welcome Center coordinates the first months of a newcomer's life in the city: intake interviews, needs assessment across housing, employment, education, language, and health, warm referrals to partner organizations, accompaniment to document and benefits appointments, enrollment in English and workforce programs, and orientation workshops. Behind every one of those interactions sits a confidentiality obligation — some clients are fleeing violence, some cases must be sealed at a moment's notice — and behind the entire operation sits a funder that pays for verified outcomes and audits the numbers.

This document specifies the API that runs that center. It governs how newcomers are registered and linked into households, how service cases move from first contact to closure under two parallel dimensions (a service pipeline and a privacy posture), how needs assessments are drafted, submitted, and verified under segregation of duties, how referrals occupy and release partner capacity, how consent grants and revocations cascade through in-flight work, how subsidized fees are computed from benefit screenings, and how outcome lines are assembled, allocated across funding streams, and defended before an external auditor.

A deliberate design constraint shapes everything below: all state is evaluated against a **logical clock** that the center controls, never against wall-clock time, so that expiry, attendance reconciliation, and reporting windows are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must carry `X-User-ID` to identify the acting party and `X-User-Role` to declare the capacity in which it acts. The system recognizes exactly six roles, spelled precisely as follows: `CenterAdmin`, `CaseManager`, `IntakeSpecialist`, `PartnerOrg`, `Client`, and `FunderAuditor`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED`. When a properly authenticated role attempts an operation that role is not permitted to perform, or fails an ownership rule attached to the resource, the request is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `CenterAdmin`, `CaseManager`, or `IntakeSpecialist`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership and authorship checks on any resource that references a `StaffMember` — for example the `author_id` of a note, the `created_by_id` of an assessment, or the `assigned_manager_id` of a case — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `PartnerOrg`, `X-User-ID` is the `id` of the acting `Organization`, and a partner may read or respond only to referrals whose `organization_id` equals its own `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; the client may read only its own record, its own cases, and its own consents, and may revoke a consent only when that consent's `client_id` equals `X-User-ID`. When `X-User-Role` is `FunderAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `reviewed_by_id` on a `FunderReport` when the auditor reviews a submission, but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`; a `limit` above 100 is silently capped at 100 rather than rejected.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties on a shared timestamp (common at a frozen logical clock) broken in creation order.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, where `has_more` is true exactly when `offset` + `limit` is still below `total_count`.

### 2.4. The Logical Clock and Scheduled Maintenance

Every time-dependent rule in the system — consent expiry, referral time-to-live, appointment no-show marking, workshop session closure, "starts in the past" validation, recent-arrival bonuses — is evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, all rules see that instant. A `CenterAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; setting the clock mutates no entity, but every subsequent sweep and time validation observes the new instant.

A second `CenterAdmin`-only capability runs the **maintenance sweep** against the current logical clock. One sweep performs five jobs: it expires `SENT` referrals whose age has reached their time-to-live, expires `GRANTED` consents whose expiry instant has passed, marks `CONFIRMED` appointments whose end has passed as `NO_SHOW`, moves `SCHEDULED` workshop sessions whose end has passed to `HELD`, and reconciles any `HELD` session whose enrollments are fully marked into `RECONCILED`. The sweep's response reports how many rows each job touched, via `referrals_expired`, `consents_expired`, `appointments_marked_no_show`, `sessions_marked_held`, and `sessions_reconciled`. The cascades each job triggers are described with their entities in §3. Every boundary test in these jobs is inclusive: a referral expires once `sent_at` plus `ttl_days` is at or before the clock, and a consent, appointment, or session whose expiry or end instant equals the clock is likewise swept.

### 2.5. Common Resource Properties

Every primary resource — clients, staff members, organizations, cases, assessments, plans, notes, consents, referrals, appointments, programs, program enrollments, workshop sessions, workshop enrollments, benefit screenings, and funder reports — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, starting at 1 at creation.

All of these entity timestamps are read from the logical clock of §2.4 — as is every stamped instant in §3 (`sent_at`, `completed_at`, `attended_marked_at`, and the like); the envelope's `api_request_timestamp` is the sole wall-clock timestamp in a response.

The one exception is the bookable `Room`: rooms carry `id` and `created_at` only. Both `updated_at` and `version` are absent from a room, because a room never mutates after creation.

Cascades obey immediate consistency: when one request mutates several resources — a privacy seal that suspends referrals and cancels appointments, a verification that supersedes an assessment and revises plans — every one of those mutations, with its refreshed `updated_at` and incremented `version` where applicable, is committed and visible in that same request's response.

### 2.6. Money, Ratios, and Rounding Discipline

All monetary quantities are integer cents. Fees, income figures, unit costs, and report totals are never fractional; where a division participates in a cents computation the result is floored to whole cents, with a single documented exception in the subsidized-fee calculation of §3.8, where the provisional fee multiplication is rounded half-up to integer cents before the burden cap is applied.

Two non-monetary quantities carry their own precision. The benefits `income_ratio` is rounded half-up to exactly four decimal places, while tier assignment itself is always decided by comparing integer cents against floored thresholds, never by comparing the rounded ratio. Acuity indices are rounded half-up to exactly one decimal place; household and recency bonuses are added after that rounding, and the final figure is then clamped. Funder-report allocation rounds each line-by-stream cell half-up to integer cents before any summation, and reconciles the residual afterwards, in the pinned order given in §3.9.

### 2.7. Optimistic Concurrency Control on Plan Creation

Exactly one write operation in the API is guarded by optimistic concurrency control: creating a case plan under a case. That request must carry `expected_case_version`, a non-optional field holding the `version` of the parent case as the client last observed it. If the case's current `version` no longer equals `expected_case_version` — because another writer has advanced the case since the client read it — the creation is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the case before superseding a plan it never saw. Within this one endpoint the payload's required fields — `title`, `budgeted_hours`, and `expected_case_version` itself — are validated before the case's `CLOSED`-state rejection of §2.8, and the version comparison fires after that state check, immediately before any existing plan is superseded. No other endpoint in the API accepts a version field.

### 2.8. Validation Order and Error Precedence

When a request violates several rules at once, the error it receives is determined by a fixed precedence ladder; the first failing rung decides the response. The rungs, in evaluation order, are:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the six declared roles; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role is permitted on the endpoint and entity-backed ownership holds: a `PartnerOrg` acts only on its own organization's referrals, a `Client` reads and revokes only its own resources, and note reads satisfy the clearance-or-authorship rule; failure yields `ERR_FORBIDDEN`. Ownership rules decidable from the request line alone — a `Client` reading its own client record — fire at this rung; ownership rules that require loading the target entity (a `Client`'s case or consent, a `PartnerOrg`'s referral) are evaluated once rung 3 has resolved the path identifier, so an unknown id surfaces as `ERR_NOT_FOUND` even when ownership would also have failed.
3. **Existence** — path identifiers (`client_id`, `staff_id`, `organization_id`, `case_id`, `assessment_id`, `plan_id`, `note_id`, `consent_id`, `referral_id`, `appointment_id`, `program_id`, `enrollment_id`, `session_id`, `wk_enrollment_id`, `screening_id`, `report_id`) are resolved first, then identifiers referenced in the body, validated left to right (in the order `client_id`, `assigned_manager_id`, `organization_id`, `room_id`, `case_id`, `program_id`, `session_id`, `advocate_id`, `referral_id`, `household_head_id` as they apply); the first unknown id yields `ERR_NOT_FOUND`.
4. **State** — the target resource sits in a valid from-state for the requested transition, terminal states reject all further transitions, and a `SUSPENDED` or `CLOSED` case rejects new child-service writes; failure yields `ERR_INVALID_STATE`.
5. **Privacy and consent gates** — the case's `privacy_posture` blocks the operation (`ERR_PRIVACY_SEALED`), a required consent scope is not `GRANTED` (`ERR_CONSENT_MISSING`), or a note's sensitivity exceeds its author's clearance (`ERR_CLEARANCE_INSUFFICIENT`).
6. **Segregation of duties** — an assessment's verifier differs from its creator; failure yields `ERR_SEGREGATION_OF_DUTIES`.
7. **Structural well-formedness** — required fields present, enum membership, score ranges, note length, end-after-start ordering, funding shares summing to one hundred, an acyclic household graph, one draft assessment per case, no duplicate live enrollments, and non-overlapping report periods; the generic failure is `ERR_INVALID_REQUEST`, with the specialized codes `ERR_HOUSEHOLD_HEAD_CYCLE`, `ERR_DRAFT_ASSESSMENT_EXISTS`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_REPORT_PERIOD_OVERLAP`, and `ERR_NOTE_TOO_LONG` for the named violations.
8. **Temporal rules** — appointment and workshop start times must not precede the logical clock (`ERR_TIME_IN_PAST`), an advocate's half-open intervals must not intersect (`ERR_ADVOCATE_TIME_CONFLICT`), and a room's buffered intervals must not intersect (`ERR_ROOM_TIME_CONFLICT`).
9. **Cross-entity state** — the client is not exited (`ERR_CLIENT_EXITED`), the case is active where required (`ERR_CASE_NOT_ACTIVE`), the partner organization is not suspended (`ERR_ORG_SUSPENDED`), the program is not closed (`ERR_PROGRAM_CLOSED`), subsidy verification and fee arrangement precede enrollment (`ERR_SUBSIDY_UNVERIFIED`, `ERR_FEE_NOT_ARRANGED`), and a warm handoff precedes referral completion (`ERR_HANDOFF_NOT_CONFIRMED`).
10. **Capacity counters** — partner referral slots (`ERR_ORG_CAPACITY_FULL`) and program seats (`ERR_PROGRAM_FULL`) are still available.

Because the ladder is ordered, a request that fails rung 3 never observes a rung-7 violation, and a mid-flight privacy hold surfaces as `ERR_PRIVACY_SEALED` rather than being masked by a later structural check.

### 2.9. Privacy Postures, Consent Scopes, and Note Clearance

Confidentiality is enforced along three independent axes. First, every case carries a `privacy_posture` of `STANDARD`, `RESTRICTED`, or `SEALED`, which gates which child-service operations may proceed against it; the transitions and cascades are specified in §3.2. Second, clients grant revocable **consents** in three scopes — `REFERRAL_SHARE` (the center may share the client's information with a referral partner), `ACCOMPANIMENT` (a staff member may accompany the client to external appointments), and `DATA_REPORTING` (the client's outcomes may appear in identifiable funder reporting). Third, case notes carry a `sensitivity` of `STANDARD`, `CONFIDENTIAL`, or `SEALED`, read respectively by staff whose `clearance_level` is at least 1, at least 2, or exactly 3 — the author's own notes always remaining readable by their author regardless of clearance.

A derived flag ties consent to reporting: a client's `reportable` is true exactly when that client holds a consent with `scope` equal to `DATA_REPORTING` in status `GRANTED`, and false otherwise. The flag is recomputed whenever a data-reporting consent is granted, revoked, or expired, and it drives the split between identifiable and aggregate-only client counts in funder reporting (§3.9).

### 2.10. Capacity Ledgers and Counter Invariants

Three capacity ledgers run continuously and must reconcile at all times. A partner organization's `referral_slots_used` always equals the count of its referrals currently occupying a slot — precisely those in `SENT` or `ACCEPTED` — and `referral_slots_open` always equals `referral_capacity` minus `referral_slots_used`, so used plus open equals capacity without exception. A workshop session's `open_seats` always equals its `capacity` minus its `enrolled_count`, with `waitlist_count` tracking the queue alongside. A program's `enrolled_count` counts only `ENROLLED` enrollments and drives the program's automatic `OPEN`/`FULL` signage. Every compensating pair of mutations — a send and a later decline, an enrollment and a later withdrawal — must preserve these invariants; §3 specifies each increment and decrement at the transition where it occurs.

## 3. Business Logic & Workflows

### 3.1. Intake: Registering Clients, Staff, Partners, and Rooms

Front-desk work begins with registration. An `IntakeSpecialist` or `CenterAdmin` registers a newcomer with the client's `full_name`, a free-text `preferred_language` (carried without code-list validation in v1), and a `date_of_birth` in `YYYY-MM-DD` form; `household_size` (persons in the household including the client, at least 1) defaults to 1, while `country_of_origin` and `arrival_date` — the date the newcomer arrived in the municipality — may be left null. A new client's `status` is `REGISTERED` and its `reportable` flag is false.

Households are expressed by pointing one client at another: the optional `household_head_id` references the head of household, and it may be supplied at registration or changed later through a household-linkage update (a null `household_head_id` in the update clears the linkage). The household graph must stay acyclic — naming the client itself, or any descendant of the client in the household chain, as `household_head_id` is rejected with `ERR_HOUSEHOLD_HEAD_CYCLE`. A successful linkage update refreshes the client's `updated_at` and increments its `version` by 1. Clients can be listed with optional `status` and `household_head_id` filters, and a `Client` reading its own record sees only that record.

A client leaves services through an explicit exit performed by a `CaseManager` or `CenterAdmin`. Exit requires that every case of the client has reached `CLOSED`; if any case is still open the request fails with `ERR_INVALID_STATE`. Once `EXITED` — the client's only terminal state — no new case may be opened for that client, and no new consent may be granted for them either; both attempts fail with `ERR_CLIENT_EXITED`.

The center's own roster is maintained by a `CenterAdmin`. Creating a staff member records `full_name`, a `role_level` of `ADMIN`, `CASE_MANAGER`, or `INTAKE`, a `clearance_level` from 1 to 3 (level 3 is required to read `SEALED` notes), and a `weekly_appointment_capacity` — a non-negative ceiling on confirmed appointments per ISO week that is informational in this version and blocks nothing. Staff members are born with `status` equal to `ACTIVE` and carry no further states in v1. Partner organizations are registered with a `name`, a non-empty `service_categories` array drawn from `HOUSING`, `EMPLOYMENT`, `EDUCATION`, `LEGAL`, and `HEALTH`, a non-negative `referral_capacity`, and a `contact_email`; a new partner is `ACTIVE` with `referral_slots_used` at 0 and `referral_slots_open` equal to its `referral_capacity`. A `CenterAdmin` may suspend a partner — an `ACTIVE`-to-`SUSPENDED` move that blocks new referral sends with `ERR_ORG_SUSPENDED` while leaving already-`SENT` or `ACCEPTED` referrals untouched — and later reactivate it. Bookable rooms, finally, are created with a unique `name` (a duplicate is `ERR_INVALID_REQUEST`) and a seat `capacity` of at least 1; the capacity is informational, since scheduling conflicts are governed by time buffers rather than seat counts.

### 3.2. The Service Case: Service Status and Privacy Posture

Opening a case for a client requires a payload carrying `client_id` and the `assigned_manager_id` of the responsible case manager, with an optional free-text `intake_summary`. The request fails with `ERR_CLIENT_EXITED` when the client has exited. A new case starts with `service_status` equal to `INTAKE` and `privacy_posture` equal to `STANDARD`; the client's own `acuity_rapid` and `acuity_verified` begin null, populated later by assessments. Creation has a welcome side effect: when a client's very first case is opened, the client automatically moves from `REGISTERED` to `ACTIVE`, with `updated_at` refreshed and `version` incremented.

The case's service pipeline runs `INTAKE` → `ASSESSED` → `PLANNING` → `ACTIVE` → `OUTCOME_REVIEW` → `CLOSED`, with a suspension loop and two entry points into review. Moving from `INTAKE` to `ASSESSED` requires at least one of the case's assessments to be `VERIFIED`, failing with `ERR_INVALID_STATE` otherwise. `ASSESSED` to `PLANNING` is unconditional. `PLANNING` to `ACTIVE` requires an `ACTIVE` case plan to exist for the case. `ACTIVE` to `SUSPENDED` is unconditional, and while a case is `SUSPENDED` the creation of new referrals, program enrollments, workshop enrollments, appointments, and screenings against it is blocked with `ERR_INVALID_STATE`. A `CLOSED` case goes further and rejects every new child-service write — assessments, plans, and notes included — with `ERR_INVALID_STATE`. Returning from `SUSPENDED` to `ACTIVE` requires that an `ACTIVE` case plan still exists. Either `ACTIVE` or `SUSPENDED` may advance to `OUTCOME_REVIEW`, but only when no referral of the case remains in `DRAFT`, `SENT`, `ACCEPTED`, or `SUSPENDED` — every referral must first reach a settled outcome. The final move from `OUTCOME_REVIEW` to `CLOSED` requires `closed_reason` in the request (its absence is `ERR_INVALID_REQUEST`) and every case plan of the case to be in `COMPLETED` or `SUPERSEDED` (otherwise `ERR_INVALID_STATE`); as the case closes, any plan still lingering in `ACTIVE` or `SUSPENDED` is forced to `COMPLETED`. Every one of these transitions is performed by a `CaseManager` or `CenterAdmin` and increments the case's `version` by 1.

The privacy dimension is orthogonal. A `CaseManager` or `CenterAdmin` may move `STANDARD` to `RESTRICTED` and back; a `RESTRICTED` case blocks referral sends with `ERR_PRIVACY_SEALED` — and, because reroutes and resumes re-run the same posture gate, it blocks those as well — but nothing else. Sealing is heavier: moving a case from `STANDARD` or `RESTRICTED` to `SEALED` is reserved to a `CenterAdmin` — any other role receives `ERR_FORBIDDEN` — and fires a four-step cascade. The case's `privacy_posture` becomes `SEALED` and its `version` increments (step one); every referral of the case in `DRAFT`, `SENT`, or `ACCEPTED` is suspended with `suspension_reason` set to `CASE_SEALED` (step two); for each referral that was holding a partner slot — those suspended out of `SENT` or `ACCEPTED` — the organization's `referral_slots_used` is decremented by 1, releasing the slot (step three); and for each suspended referral, every appointment whose `referral_id` names it and whose status is `REQUESTED` or `CONFIRMED` is cancelled with `cancelled_by_system` set to true (step four). A sealed case blocks referral sends, resumes, and reroutes, appointment creation, screening creation, and — for anyone other than a `CenterAdmin` — note creation, all with `ERR_PRIVACY_SEALED`. Unsealing moves `SEALED` back to `RESTRICTED` (again `CenterAdmin`-only) and deliberately does not resurrect anything: referrals suspended by the seal remain `SUSPENDED` until a case manager explicitly resumes them. Both privacy moves are requested with `to_posture` and a `reason`, and each increments the case's `version` by 1.

Case notes ride on this privacy dimension. An `IntakeSpecialist`, `CaseManager`, or `CenterAdmin` appends a note to a case with `case_id`, the note `body`, and a `sensitivity` classification; the author's `X-User-ID` is recorded as `author_id`. The `body` runs from 1 to 10000 characters — anything outside that range is rejected with `ERR_NOTE_TOO_LONG` — and the chosen `sensitivity` may not exceed the author's own `clearance_level`, an overreach rejected with `ERR_CLEARANCE_INSUFFICIENT` (an author whose `X-User-ID` matches no staff member has no clearance at all and is rejected with `ERR_FORBIDDEN`). On a `SEALED` case, note creation is reserved to a `CenterAdmin`; other roles meet `ERR_PRIVACY_SEALED`. A note is born with `redaction_status` equal to `VISIBLE`, and a `CenterAdmin` may later redact it by supplying a `reason`, moving it to the terminal `REDACTED` state; redaction masks the `body` — returned as null — on every subsequent read, for author, administrator, and auditor alike, while the authorship and sensitivity metadata are retained. Reads of unmasked notes follow the clearance-or-authorship rule of §2.9, applied row by row when notes are listed by `case_id` or `author_id`.

### 3.3. Needs Assessments, Acuity, and Verification Duties

Assessment begins at intake. An `IntakeSpecialist` or `CaseManager` drafts a needs assessment for a case by supplying `case_id` and five severity scores — `housing_score`, `employment_score`, `education_score`, `language_score`, and `health_score` — each an integer from 0 to 4. The creator's `X-User-ID` is recorded as `created_by_id`, which becomes the segregation-of-duties anchor. A case may hold at most one assessment in `DRAFT` at a time; a second draft attempt fails with `ERR_DRAFT_ASSESSMENT_EXISTS`.

Submitting a draft (performed by any `IntakeSpecialist` or `CaseManager`, not necessarily the creator; a non-`DRAFT` assessment yields `ERR_INVALID_STATE`) moves it to `SUBMITTED` and recomputes the case's `acuity_rapid` using the rapid variant below. Verification is the gate that turns self-report into case-of-record: a `CaseManager` or `CenterAdmin` verifies a `SUBMITTED` assessment, and the verifier must not be the creator — an `X-User-ID` equal to the assessment's `created_by_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Verification stamps `verified_by_id` with the verifier's `X-User-ID`, then cascades: the case's previously `VERIFIED` assessment, if one exists, becomes `SUPERSEDED`; every case plan of the case that is `ACTIVE` or `SUSPENDED` and whose `basis_assessment_id` names the just-superseded assessment is pushed back to `DRAFT` with its `plan_revision` incremented by 1; and both acuity indices are recomputed from the newly verified assessment — the comprehensive variant feeding `acuity_verified` and the rapid variant refreshing `acuity_rapid`.

Both acuity variants share one base. Each domain score is divided by four and multiplied by its weight — 0.30 for housing, 0.25 for employment, 0.15 for education, 0.20 for language, 0.10 for health — and the five weighted contributions are summed into a base index between zero and one. The **rapid** variant, used at submission and whenever a not-yet-verified assessment is the latest, multiplies the base by one hundred and rounds half-up to one decimal place; it applies no multiplier and no bonuses. The **comprehensive** variant, used only on verified assessments, first multiplies the base by 1.25 and caps that product at one, then multiplies by one hundred and rounds half-up to one decimal place; it then adds ten points when the client's `household_size` is at least 5, and five more points when the client's `arrival_date` is set and lies no more than 90 days before the current logical clock (the test is one-sided, so an `arrival_date` equal to or after the clock also earns the bonus). Bonuses are added after the rounding step, and the final figure is clamped so it never falls below 0 or above 100. A case's `acuity_rapid` always reflects its latest `SUBMITTED` or `VERIFIED` assessment, and `acuity_verified` its latest `VERIFIED` one; both stay null until the corresponding event first occurs.

### 3.4. Case Plans and Optimistic Replanning

A case plan is created under its case, and creation is the one OCC-guarded write in the system: the request carries `title`, `budgeted_hours` (at least 1 staff service hour), and `expected_case_version` holding the case `version` the client last observed, per §2.7. Creation supersedes the case's current plan — whether that plan sits in `DRAFT`, `ACTIVE`, or `SUSPENDED`, it becomes `SUPERSEDED` — and increments the case's `version` by 1. The new plan starts in `DRAFT` with `plan_revision` at 1 and `basis_assessment_id` null. Because plan creation legitimately replaces whatever plan exists, the stale-version rejection with `ERR_STALE_CASE_VERSION` is the intended serialization point between a writer and a case that has moved on.

Activation moves a plan from `DRAFT` to `ACTIVE` and pins its evidentiary basis: the parent case must be in `PLANNING`, `ACTIVE`, or `SUSPENDED`, a `VERIFIED` assessment must exist for the case, and `basis_assessment_id` is set to the `id` of the case's current `VERIFIED` assessment — the one with the latest `updated_at`, a tie being impossible because verification always refreshes that timestamp. From `ACTIVE` a plan may be suspended (`ACTIVE` → `SUSPENDED`), resumed (`SUSPENDED` → `ACTIVE`, which requires the parent case not to be `CLOSED` and refreshes `basis_assessment_id` to the case's current verified assessment, retaining the prior `basis_assessment_id` when no `VERIFIED` assessment exists), completed (`ACTIVE` or `SUSPENDED` → `COMPLETED`), or revised back to `DRAFT`. Revision arrives by two paths: an explicit revise by a `CaseManager` or `CenterAdmin`, or the automatic path of §3.3 when the plan's basis assessment is superseded by a newer verification. Either path increments `plan_revision` by 1. Plans are terminal in `COMPLETED` or `SUPERSEDED`, and every explicit transition request names its target via `to_status`.

### 3.5. Consents, Referrals, and the Warm Handoff Pipeline

Consent is the legal substrate of the referral pipeline. An `IntakeSpecialist`, `CaseManager`, or `CenterAdmin` grants a consent for a client with `client_id`, a `scope`, and an optional `expires_at` instant; the consent is born `GRANTED`, and granting one with `scope` equal to `DATA_REPORTING` recomputes the client's `reportable` flag. Granting a consent for an `EXITED` client is refused with `ERR_CLIENT_EXITED`. Revocation — by a `CaseManager`, a `CenterAdmin`, or the client itself acting on its own consent — is valid only from `GRANTED` (anything else is `ERR_INVALID_STATE`); it captures an optional `revoked_reason`, moves the consent to `REVOKED`, and recomputes `reportable`. When the revoked consent's scope is `REFERRAL_SHARE`, the same three-step cascade as a privacy seal follows: every referral of the client's cases in `SENT` or `ACCEPTED` is suspended with `suspension_reason` set to `CONSENT_REVOKED`, each such suspension decrements the partner's `referral_slots_used` by 1, and each suspended referral cancels its linked `REQUESTED` or `CONFIRMED` appointments with `cancelled_by_system` true. The maintenance sweep produces the identical cascade when it flips a `GRANTED` consent whose `expires_at` has passed to `EXPIRED` — a consent-expiry suspension is likewise recorded as `CONSENT_REVOKED`.

A referral is drafted by a `CaseManager` or `CenterAdmin` with `case_id`, `organization_id`, a `service_category`, and optional handoff `notes` and `ttl_days`. The category must appear in the partner's `service_categories` or creation fails with `ERR_INVALID_REQUEST`. `ttl_days` defaults to 14 and must be at least 1; it is the number of days a referral may sit in `SENT` before the sweep expires it. A draft referral holds no partner slot.

Sending is the gated heart of the pipeline, reserved to a `CaseManager`. Six conditions must hold, and §2.8 fixes the order in which they surface: the referral is `DRAFT` (else `ERR_INVALID_STATE`); the case's `privacy_posture` is `STANDARD` (else `ERR_PRIVACY_SEALED`); the client holds a `GRANTED` consent with `scope` equal to `REFERRAL_SHARE` (else `ERR_CONSENT_MISSING`); the partner is `ACTIVE` (else `ERR_ORG_SUSPENDED`); the partner's `referral_slots_used` is below its `referral_capacity` (else `ERR_ORG_CAPACITY_FULL`); and the case is neither `SUSPENDED` nor `CLOSED` (else `ERR_INVALID_STATE`). A successful send stamps `sent_at` with the current logical clock and increments the organization's `referral_slots_used` by 1.

The partner then responds. A `PartnerOrg` may accept or decline, but only for referrals addressed to its own organization — a mismatch between the referral's `organization_id` and the actor's `X-User-ID` is `ERR_FORBIDDEN` — and only while the referral is `SENT` (else `ERR_INVALID_STATE`). The response payload carries a `decision` of `ACCEPTED` or `DECLINED` and, on acceptance, may set `warm_handoff_offered` (default false) to flag that the partner will receive the client personally. Either response stamps `responded_at`; a decline additionally releases the partner slot, decrementing `referral_slots_used` by 1.

A referral that stalls dies quietly: when the sweep finds a `SENT` referral whose `sent_at` plus its `ttl_days` has been reached by the logical clock, the referral becomes `EXPIRED` and its slot is released. Neither `DECLINED` nor `EXPIRED` is terminal, because the case manager may reroute: rerouting names a new `organization_id`, which must differ from the current one and must list the referral's `service_category` among its `service_categories` (both violations are `ERR_INVALID_REQUEST`), and then re-runs the full battery of send gates — posture, consent, partner status, partner capacity, case status. A successful reroute replaces `organization_id`, restamps `sent_at` (any `responded_at` from the prior cycle is retained), and increments the new organization's `referral_slots_used` by 1; a rerouted referral is once again `SENT`.

Completion is the paying outcome. Before an `ACCEPTED` referral can complete, the warm handoff must be confirmed — a `CaseManager` or `CenterAdmin` records the confirmation, valid only while the referral is `ACCEPTED` (otherwise `ERR_INVALID_STATE`), which stamps `handoff_confirmed_at` — and completing without it fails with `ERR_HANDOFF_NOT_CONFIRMED`. Completion stamps `completed_at` with the logical clock (this instant later keys the funder outcome window of §3.9) and releases the partner slot. Withdrawal, available to a `CaseManager` or `CenterAdmin` from `DRAFT`, `SENT`, `ACCEPTED`, or `SUSPENDED`, is the other way out: withdrawing from `SENT` or `ACCEPTED` releases the slot, while withdrawing from `SUSPENDED` changes no counters because the slot was already released at suspension, and `DRAFT` never held one. Resuming, finally, returns a `SUSPENDED` referral to `SENT` once the privacy or consent blocker has cleared; it is a `CaseManager` action gated by the same posture, consent, partner-status, and partner-capacity checks as a send, and it clears `suspension_reason` to null, restamps `sent_at`, and re-occupies a partner slot. `COMPLETED` and `WITHDRAWN` are the referral's terminal states.

### 3.6. Appointments, Documents, and Accompaniment

Appointments cover the face-to-face work of the center: document and ID assistance, accompaniment to outside agencies, orientation, and benefits counseling. Scheduling one requires `case_id`, the `advocate_id` of the accompanying or assisting staff member, a `kind` of `DOCUMENT_ID`, `ACCOMPANIMENT`, `ORIENTATION`, or `BENEFITS`; it also requires the half-open interval from `starts_at` (inclusive) to `ends_at` (exclusive), with an optional `referral_id` linking the appointment to a referral handoff. `ends_at` must fall after `starts_at` (`ERR_INVALID_REQUEST`), and `starts_at` must not precede the current logical clock (`ERR_TIME_IN_PAST`). Creating an appointment on a `SEALED` case is blocked with `ERR_PRIVACY_SEALED`, and creating one on a `SUSPENDED` case with `ERR_INVALID_STATE`.

An advocate's calendar is protected by half-open interval arithmetic: a new appointment conflicts when another appointment with the same `advocate_id` sits in `REQUESTED` or `CONFIRMED` and the intervals genuinely overlap — that is, the new `ends_at` falls after the existing `starts_at` while the new `starts_at` falls before the existing `ends_at`. Adjacency is explicitly permitted: a new appointment starting exactly when an existing one ends (or ending exactly when one starts) does not conflict. A genuine overlap is rejected with `ERR_ADVOCATE_TIME_CONFLICT`. A new appointment is born `REQUESTED`.

Confirmation — a `CaseManager` or `CenterAdmin` action moving `REQUESTED` to `CONFIRMED` — carries one consent gate: when the appointment's `kind` is `ACCOMPANIMENT`, the client must hold a `GRANTED` consent with `scope` equal to `ACCOMPANIMENT`, failing with `ERR_CONSENT_MISSING` otherwise. From `CONFIRMED` the appointment is either completed (stamping `completed_at` with the logical clock) or, if its `ends_at` passes with no completion recorded, marked `NO_SHOW` by the sweep. Cancellation is possible from `REQUESTED` or `CONFIRMED`; an explicit cancel leaves `cancelled_by_system` false, while the privacy and consent cascades of §3.2 and §3.5 cancel linked appointments with `cancelled_by_system` set to true — which is how an audit distinguishes staff decisions from protective automation. The appointment's terminal states are `COMPLETED`, `CANCELLED`, and `NO_SHOW`.

### 3.7. Benefits Screening and Eligibility Tiering

Screening translates a household's finances into benefit eligibility. An `IntakeSpecialist` or `CaseManager` opens a screening for a case with `case_id` and the client's self-reported, non-negative `stated_annual_income_cents`; creation snapshots the client's `household_size` onto the screening at that moment, and the screening starts in `DRAFT`. Creating a screening against a `SEALED` case is blocked with `ERR_PRIVACY_SEALED`, and against a `SUSPENDED` case with `ERR_INVALID_STATE`.

Running a draft screening moves it to `SCREENED` and evaluates the **self-reported** variant: `variant_used` becomes `SELF_REPORTED` and the computed trio — `income_ratio`, `tier`, and `eligible_programs` — is populated. Later, a `CaseManager` attaches document-verified income by supplying a non-negative `documented_annual_income_cents`; this verification is accepted only from `SCREENED` and leaves the screening in `SCREENED`, but flips `variant_used` to `VERIFIED` and recomputes the trio under the verified variant. Two further `CaseManager` actions complete the loop: explaining records that the results were walked through with the client, moving `SCREENED` to `EXPLAINED`; and reopening returns a `SCREENED` screening to `DRAFT`, clearing `tier` and `income_ratio` to null and `eligible_programs` to an empty array for a fresh pass. These are the only transitions: an `EXPLAINED` screening has no outgoing moves in v1 — it can be neither verified nor reopened directly.

Tiering works against the federal poverty guideline, expressed as annual cents by household size: 1506000 for one person, 2044000 for two, 2582000 for three, 3120000 for four, 3658000 for five, 4196000 for six, 4734000 for seven, and 5272000 for eight; households larger than eight use the eight-person figure. The `income_ratio` is the applicable income — stated income for the self-reported variant, documented income for the verified variant — divided by the guideline for the snapshotted household size, rounded half-up to four decimal places. Tier assignment ignores the rounded ratio and instead compares integer income cents against floored guideline multiples: `TIER_A` when income is no greater than the floored value of 138 percent of the guideline; `TIER_B` when income exceeds that floor but not the floored 200 percent; `TIER_C` when income exceeds the floored 200 percent but not the floored 300 percent; and `TIER_D` otherwise. Each tier carries a program set: `TIER_A` yields `SNAP`, `MEDICAID`, `CASH_ASSIST`, and `ESL_SUBSIDY`; `TIER_B` yields `SNAP` and `ESL_SUBSIDY`; `TIER_C` yields `ESL_SUBSIDY` alone; and `TIER_D` yields an empty set, which is a valid no-match outcome. The variant then filters the set: the self-reported variant strips `CASH_ASSIST` — cash assistance is documentation-gated — while the verified variant keeps the full tier set.

### 3.8. Programs, Workshops, and Enrollment Management

The center runs English classes and workforce programs. A `CenterAdmin` creates a program with a `name`, a `kind` of `ESOL` or `WORKFORCE`, a seat `capacity` of at least 1, a non-negative `base_fee_cents` list price before subsidy, and a likewise non-negative `cost_per_completion_cents` — the funder-costed value of one completion. A new program is `OPEN` with `enrolled_count` at 0; it automatically becomes `FULL` the moment `enrolled_count` reaches `capacity`, and automatically reopens (`FULL` → `OPEN`) when a withdrawal or completion drops the count back below. Closing a program — from either `OPEN` or `FULL` — is a `CenterAdmin` action with a teach-out rule: enrollments still in `APPLIED` or `ELIGIBLE` are denied with `denial_reason` set to `PROGRAM_CLOSED`, while `ENROLLED` participants are unaffected and finish their course.

Applying a case to a program is open to `CaseManager` and `IntakeSpecialist` via a payload of `case_id` and `program_id`. The case must be `ACTIVE` (else `ERR_CASE_NOT_ACTIVE`), the program must not be `CLOSED` (else `ERR_PROGRAM_CLOSED`), and no live enrollment may already exist for the pair — a duplicate in `APPLIED`, `ELIGIBLE`, or `ENROLLED` is rejected with `ERR_DUPLICATE_ENROLLMENT`. A new enrollment is `APPLIED` with `fee_status` equal to `PENDING` and both subsidy fields null.

Eligibility determination moves `APPLIED` to `ELIGIBLE`. When the program's `base_fee_cents` is greater than zero, the case must hold a benefit screening in `SCREENED` or `EXPLAINED` whose `variant_used` is `VERIFIED`; without one the transition fails with `ERR_SUBSIDY_UNVERIFIED`. The subsidized fee is then computed in a pinned order. First, the tier is read from the case's latest verified screening — the one with `variant_used` equal to `VERIFIED` and the greatest `updated_at`, ties breaking toward the later-created screening. Second, the tier maps to a base subsidy percentage: 0.90 for `TIER_A`, 0.60 for `TIER_B`, 0.30 for `TIER_C`, and 0.00 for `TIER_D`. Third, the provisional fee is `base_fee_cents` multiplied by one minus that percentage, rounded half-up to whole cents. Fourth, the client's monthly income is the screening's `documented_annual_income_cents` divided by 12 and floored, and the burden cap is that monthly income multiplied by 0.05 and floored. Fifth, the final fee is the smaller of the provisional fee and the burden cap, never below zero. The recorded `subsidy_pct` is always the tier's base percentage — even when the burden cap binds and reduces the fee further — and `subsidized_fee_cents` is the final fee. When the program is free (`base_fee_cents` of zero), no screening is required, `subsidized_fee_cents` is simply 0, and `subsidy_pct` stays null. Eligibility sets `fee_status` to `WAIVED` when the final fee is zero and leaves it `PENDING` otherwise; a `CaseManager` records a fee arrangement to move `PENDING` to `ARRANGED`, an attempt that fails with `ERR_INVALID_STATE` unless the enrollment is `ELIGIBLE` with a `PENDING` fee.

Enrollment proper moves `ELIGIBLE` to `ENROLLED` and requires three things beyond state: the program is not `CLOSED` (`ERR_PROGRAM_CLOSED`), the fee is settled with `fee_status` in `ARRANGED` or `WAIVED` (`ERR_FEE_NOT_ARRANGED`), and a seat exists with the program's `enrolled_count` below its `capacity` (`ERR_PROGRAM_FULL`). Success increments `enrolled_count` by 1, possibly tripping the automatic `OPEN` → `FULL` signage. From `ENROLLED`, a withdrawal decrements the count and may trip `FULL` → `OPEN`, while a completion stamps `completed_at` with the logical clock — the funder outcome key of §3.9 — and likewise decrements the count. Denial from `APPLIED` or `ELIGIBLE` accepts an optional `denial_reason`. `COMPLETED`, `WITHDRAWN`, and `DENIED` are terminal, and all enrollment moves are requested through `to_status` by a `CaseManager` or `CenterAdmin`, save applications and fee arrangements as noted above.

Orientation workshops run on a parallel, simpler track. A `CaseManager` or `CenterAdmin` schedules a session with `room_id`, `title`, a seat `capacity` of at least 1, and `starts_at`/`ends_at`; the session is born `SCHEDULED` with `enrolled_count`, `waitlist_count` at 0 and `open_seats` equal to `capacity`. Rooms are protected by buffered closed intervals: each session occupies from 15 minutes before its `starts_at` to 15 minutes after its `ends_at`, both endpoints inclusive, as turnover time. A new session conflicts when another session in the same room, in `SCHEDULED` or `HELD`, has buffered intervals that touch or overlap — the new buffered start at or before the existing buffered end, and the existing buffered start at or before the new buffered end — and is rejected with `ERR_ROOM_TIME_CONFLICT`. Because the endpoints are inclusive, a back-to-back session always conflicts, and even a gap of exactly 30 minutes conflicts; a gap strictly greater than 30 minutes is required between sessions in one room. Session `starts_at` values must not precede the logical clock (`ERR_TIME_IN_PAST`), and `ends_at` must follow `starts_at`.

Enrolling a case in a session takes `session_id` and `case_id`; the session must still be `SCHEDULED` — enrolling into a `HELD`, `RECONCILED`, or `CANCELLED` session fails with `ERR_INVALID_STATE`. When `enrolled_count` has reached `capacity`, the newcomer is `WAITLISTED` and receives the next per-session `waitlist_position` — a monotonic sequence 1, 2, 3, … in creation order; otherwise the enrollment is `ENROLLED` and `enrolled_count` increments. A case may not hold two live enrollments in one session — `ENROLLED` or `WAITLISTED` duplicates fail with `ERR_DUPLICATE_ENROLLMENT`. Cancelling an `ENROLLED` enrollment frees a seat: `enrolled_count` decrements, `open_seats` increments, and exactly one waitlisted enrollment is promoted — the one with the lowest `waitlist_position` — moving to `ENROLLED` (the promoted enrollment keeps its `waitlist_position` value) with `waitlist_count` decrementing and `enrolled_count` and `open_seats` adjusting accordingly; an empty waitlist promotes nobody. Cancelling a `WAITLISTED` enrollment simply decrements `waitlist_count` with no promotion, since no seat was held. Cancelling the session itself — permitted only while `SCHEDULED` — cascades every `ENROLLED` and `WAITLISTED` enrollment to `CANCELLED` and zeroes the counters, leaving `open_seats` equal to `capacity`.

Time closes the loop. The sweep moves a `SCHEDULED` session to `HELD` once its `ends_at` has passed. Only then may a `CaseManager` mark attendance, and only for `ENROLLED` enrollments: supplying `attended` true marks `ATTENDED` and stamps `attended_marked_at` with the logical clock (the funder outcome key for workshops), while false marks `NO_SHOW`; either way the seat is released after the fact, decrementing `enrolled_count` and incrementing `open_seats`. Once every `ENROLLED` enrollment of a `HELD` session has been marked one way or the other, the sweep reconciles the session to `RECONCILED`; a `HELD` session with no `ENROLLED` enrollments at all satisfies this vacuously and reconciles in the same sweep that marked it `HELD`. Terminal states: `CANCELLED` and `RECONCILED` close a session, while `CANCELLED`, `ATTENDED`, and `NO_SHOW` close an enrollment.

### 3.9. Funder Reporting and the Outcome Audit

Reporting monetizes the terminal outcomes of §3.5 through §3.8. A `CenterAdmin` drafts a funder report with `period_start` (inclusive), `period_end` (exclusive, and it must fall after `period_start` or the request is `ERR_INVALID_REQUEST`), and a `funding_streams` array whose elements each name a `stream_name` and a `share_pct`; each `share_pct` is a JSON number, and the shares must sum to exactly 100. The period must not overlap any existing report whose status is not `RETURNED` — overlaps are rejected with `ERR_REPORT_PERIOD_OVERLAP`. A new report is `DRAFT`, and its outcome lines, stream totals, and client counts are computed immediately at creation.

Line assembly counts three outcome types within the half-open window from `period_start` to `period_end`: referrals whose status is `COMPLETED` with `completed_at` in the window, costed at 7500 cents apiece; program enrollments `COMPLETED` with `completed_at` in the window, at 12000 cents apiece; and workshop enrollments `ATTENDED` with `attended_marked_at` in the window, at 2500 cents apiece. The stored `lines` array lists the three line types in the order given above. Each line carries its `line_type`, `unit_cost_cents`, `quantity`, and a `line_total_cents` of quantity times unit cost, and `total_cost_cents` sums the line totals. Allocation then proceeds in a pinned order: for each line and each stream, taken in `funding_streams` array order, the cell value is the line total multiplied by the stream's `share_pct`, divided by 100, and rounded half-up to integer cents — rounding happens per cell, before any summation; each stream's total is the sum of its cells. Because per-cell rounding rarely sums exactly, the residual — `total_cost_cents` minus the sum of all stream totals — is assigned, even when negative, to the stream with the greatest `share_pct`; ties break to the stream appearing earliest in the `funding_streams` array, never to any entity id. The result is stored as `stream_totals`, one entry per funding stream, each entry carrying the stream's `stream_name`, its `share_pct` echoed from the report's `funding_streams` input, and its computed `total_cents` — the sum of that stream's cells plus any residual assigned to it. Two client counts accompany the money: `aggregate_client_count` counts distinct clients behind the counted rows regardless of consent, while `reportable_client_count` counts only distinct clients whose `reportable` flag is true — the consent split that keeps non-consented clients in aggregate-only figures. A stored `lines` array, `stream_totals`, and the counts may be recomputed at any time for a `DRAFT` or `RETURNED` report through regeneration.

Submission is a freshness checkpoint, performed by a `CenterAdmin` from `DRAFT` or `RETURNED`: the server recomputes the lines at submit time, and if the recomputation differs from the stored `lines` the submission fails with `ERR_REPORT_STALE` — the remedy is to regenerate first. A successful submission stamps `submitted_by_id` with the actor's `X-User-ID`; resubmission of a previously returned report additionally clears `reviewed_by_id` to null. Review belongs to the `FunderAuditor`, whose `decision` of `ACCEPTED` or `RETURNED` is valid only against a `SUBMITTED` report and stamps `reviewed_by_id`. Acceptance is terminal; a returned report re-enters the draft cycle through regeneration and resubmission.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, transition, or otherwise modify an existing resource return `200 OK`. Error responses use the codes catalogued in §5. The table below is a navigational index only — request payloads, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | CenterAdmin |
| POST | `/_sweeps/run` | Run the maintenance sweep against the logical clock | CenterAdmin |
| POST | `/clients` | Register a newcomer | IntakeSpecialist, CenterAdmin |
| GET | `/clients/{client_id}` | Get a client; Client role reads only its own record | CenterAdmin, CaseManager, IntakeSpecialist, Client |
| GET | `/clients` | List clients with pagination | CenterAdmin, CaseManager, IntakeSpecialist, Client |
| POST | `/clients/{client_id}/exit` | Exit a client from services; requires all cases CLOSED | CaseManager, CenterAdmin |
| PATCH | `/clients/{client_id}` | Update household linkage (`household_head_id`) | IntakeSpecialist, CaseManager, CenterAdmin |
| POST | `/staff` | Create a staff member | CenterAdmin |
| GET | `/staff/{staff_id}` | Get a staff member | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/organizations` | Register a referral partner organization | CenterAdmin |
| GET | `/organizations/{organization_id}` | Get an organization | CenterAdmin, CaseManager, IntakeSpecialist, PartnerOrg |
| POST | `/organizations/{organization_id}/suspend` | Suspend a partner (blocks new sends; existing referrals untouched) | CenterAdmin |
| POST | `/organizations/{organization_id}/reactivate` | Reactivate a suspended partner | CenterAdmin |
| POST | `/rooms` | Create a bookable room | CenterAdmin |
| POST | `/cases` | Open a service case for a client | IntakeSpecialist, CaseManager, CenterAdmin |
| GET | `/cases/{case_id}` | Get a case; Client role reads only its own | CenterAdmin, CaseManager, IntakeSpecialist, Client |
| GET | `/cases` | List cases with filters | CenterAdmin, CaseManager, IntakeSpecialist, Client |
| POST | `/cases/{case_id}/transition` | Advance the service_status dimension | CaseManager, CenterAdmin |
| POST | `/cases/{case_id}/privacy` | Move the privacy_posture dimension; SEALED cascades | CaseManager, CenterAdmin |
| POST | `/assessments` | Create a DRAFT needs assessment (one DRAFT per case) | IntakeSpecialist, CaseManager |
| GET | `/assessments/{assessment_id}` | Get an assessment | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/assessments` | List assessments, filterable by case | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/assessments/{assessment_id}/submit` | Submit a DRAFT assessment; recomputes acuity_rapid | IntakeSpecialist, CaseManager |
| POST | `/assessments/{assessment_id}/verify` | Verify a SUBMITTED assessment (verifier differs from creator) | CaseManager, CenterAdmin |
| POST | `/cases/{case_id}/plans` | Create a CasePlan under a case; supersedes the current plan; OCC on Case version | CaseManager, CenterAdmin |
| GET | `/plans/{plan_id}` | Get a plan | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/plans` | List plans, filterable by case | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/plans/{plan_id}/transition` | Plan lifecycle transitions | CaseManager, CenterAdmin |
| POST | `/case-notes` | Append a case note under clearance and posture rules | IntakeSpecialist, CaseManager, CenterAdmin |
| GET | `/case-notes/{note_id}` | Read a note; clearance or authorship required; REDACTED masks body | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/case-notes` | List notes, filterable by case or author | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/case-notes/{note_id}/redact` | Redact a note | CenterAdmin |
| POST | `/consents` | Grant a consent scope for a client | IntakeSpecialist, CaseManager, CenterAdmin |
| GET | `/consents/{consent_id}` | Get a consent; Client role reads only its own | CenterAdmin, CaseManager, IntakeSpecialist, Client |
| GET | `/consents` | List consents with filters | CenterAdmin, CaseManager, IntakeSpecialist, Client |
| POST | `/consents/{consent_id}/revoke` | Revoke a consent; REFERRAL_SHARE revocation cascades | CaseManager, CenterAdmin, Client |
| POST | `/referrals` | Create a DRAFT referral to a partner organization | CaseManager, CenterAdmin |
| GET | `/referrals/{referral_id}` | Get a referral; PartnerOrg reads only its own organization's | CenterAdmin, CaseManager, IntakeSpecialist, PartnerOrg |
| GET | `/referrals` | List referrals with filters | CenterAdmin, CaseManager, IntakeSpecialist, PartnerOrg |
| POST | `/referrals/{referral_id}/send` | Send a DRAFT referral through the posture/consent/org/slot gates | CaseManager |
| POST | `/referrals/{referral_id}/respond` | Partner accepts or declines a SENT referral | PartnerOrg |
| POST | `/referrals/{referral_id}/confirm-handoff` | Confirm the warm handoff occurred | CaseManager, CenterAdmin |
| POST | `/referrals/{referral_id}/complete` | Complete an ACCEPTED referral after handoff confirmation | CaseManager, CenterAdmin |
| POST | `/referrals/{referral_id}/withdraw` | Withdraw a referral in DRAFT, SENT, ACCEPTED, or SUSPENDED | CaseManager, CenterAdmin |
| POST | `/referrals/{referral_id}/reroute` | Re-route a DECLINED or EXPIRED referral to a different organization | CaseManager |
| POST | `/referrals/{referral_id}/resume` | Resume a SUSPENDED referral once the blocker clears | CaseManager |
| POST | `/appointments` | Schedule a document, accompaniment, orientation, or benefits appointment | CaseManager, IntakeSpecialist, CenterAdmin |
| GET | `/appointments/{appointment_id}` | Get an appointment | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/appointments` | List appointments with filters | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/appointments/{appointment_id}/confirm` | Confirm a REQUESTED appointment | CaseManager, CenterAdmin |
| POST | `/appointments/{appointment_id}/cancel` | Cancel a REQUESTED or CONFIRMED appointment | CaseManager, CenterAdmin |
| POST | `/appointments/{appointment_id}/complete` | Complete a CONFIRMED appointment | CaseManager, CenterAdmin |
| POST | `/programs` | Create an ESOL or workforce program | CenterAdmin |
| GET | `/programs/{program_id}` | Get a program | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/programs/{program_id}/close` | Close a program; APPLIED/ELIGIBLE enrollments denied (teach-out) | CenterAdmin |
| POST | `/program-enrollments` | Apply a case to a program (case must be ACTIVE) | CaseManager, IntakeSpecialist |
| GET | `/program-enrollments/{enrollment_id}` | Get a program enrollment | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/program-enrollments` | List program enrollments with filters | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/program-enrollments/{enrollment_id}/transition` | Move an enrollment through its lifecycle | CaseManager, CenterAdmin |
| POST | `/program-enrollments/{enrollment_id}/arrange-fee` | Record a fee arrangement for a PENDING fee | CaseManager |
| POST | `/workshop-sessions` | Schedule an orientation workshop session in a room | CaseManager, CenterAdmin |
| GET | `/workshop-sessions/{session_id}` | Get a session | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/workshop-sessions` | List sessions with filters | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/workshop-sessions/{session_id}/cancel` | Cancel a SCHEDULED session; cascades to enrollments | CaseManager, CenterAdmin |
| POST | `/workshop-enrollments` | Enroll a case in a workshop session; over-capacity rows waitlist | CaseManager, IntakeSpecialist |
| GET | `/workshop-enrollments/{wk_enrollment_id}` | Get a workshop enrollment | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/workshop-enrollments` | List workshop enrollments with filters | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/workshop-enrollments/{wk_enrollment_id}/cancel` | Cancel an enrollment; promotes the waitlist head when a seat frees | CaseManager, CenterAdmin |
| POST | `/workshop-enrollments/{wk_enrollment_id}/mark-attendance` | Mark an ENROLLED enrollment ATTENDED or NO_SHOW once HELD | CaseManager |
| POST | `/benefit-screenings` | Create a DRAFT benefits screening (snapshots household size) | IntakeSpecialist, CaseManager |
| GET | `/benefit-screenings/{screening_id}` | Get a screening | CenterAdmin, CaseManager, IntakeSpecialist |
| GET | `/benefit-screenings` | List screenings, filterable by case | CenterAdmin, CaseManager, IntakeSpecialist |
| POST | `/benefit-screenings/{screening_id}/run` | Run the self-reported eligibility variant | IntakeSpecialist, CaseManager |
| POST | `/benefit-screenings/{screening_id}/verify` | Attach documented income and recompute the verified variant | CaseManager |
| POST | `/benefit-screenings/{screening_id}/explain` | Record that results were explained to the client | CaseManager |
| POST | `/benefit-screenings/{screening_id}/reopen` | Reopen a SCREENED screening back to DRAFT | CaseManager |
| POST | `/funder-reports` | Create a DRAFT funder report for a non-overlapping period | CenterAdmin |
| GET | `/funder-reports/{report_id}` | Get a funder report | CenterAdmin, FunderAuditor |
| GET | `/funder-reports` | List funder reports | CenterAdmin, FunderAuditor |
| POST | `/funder-reports/{report_id}/regenerate` | Recompute lines and totals for a DRAFT or RETURNED report | CenterAdmin |
| POST | `/funder-reports/{report_id}/submit` | Submit a report; recomputation must match stored lines | CenterAdmin |
| POST | `/funder-reports/{report_id}/review` | Auditor accepts or returns a SUBMITTED report | FunderAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_PRIVACY_SEALED` | 409 |
| `ERR_CONSENT_MISSING` | 409 |
| `ERR_CLEARANCE_INSUFFICIENT` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_HOUSEHOLD_HEAD_CYCLE` | 409 |
| `ERR_DRAFT_ASSESSMENT_EXISTS` | 409 |
| `ERR_NOTE_TOO_LONG` | 422 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_TIME_IN_PAST` | 409 |
| `ERR_ADVOCATE_TIME_CONFLICT` | 409 |
| `ERR_ROOM_TIME_CONFLICT` | 409 |
| `ERR_CLIENT_EXITED` | 409 |
| `ERR_CASE_NOT_ACTIVE` | 409 |
| `ERR_ORG_SUSPENDED` | 409 |
| `ERR_ORG_CAPACITY_FULL` | 409 |
| `ERR_PROGRAM_CLOSED` | 409 |
| `ERR_PROGRAM_FULL` | 409 |
| `ERR_SUBSIDY_UNVERIFIED` | 409 |
| `ERR_FEE_NOT_ARRANGED` | 409 |
| `ERR_HANDOFF_NOT_CONFIRMED` | 409 |
| `ERR_REPORT_STALE` | 409 |
