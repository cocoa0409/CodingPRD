# Community Center Registration API — Product Requirements Document

## 1. Introduction

A municipal community center runs its programming in seasons: a catalog of programs is assembled, residents receive first access to limited seats, scholarships soften fees for qualifying households, instructors are contracted and paid per counted participant, and rooms are scheduled against hard capacity and turnover constraints. This document specifies the API that operates that entire cycle — seasonal catalog and class capacity management, resident versus non-resident pricing with priority registration windows, scholarship application review under a season budget, instructor contracting and settlement, room assignment with conflict management, minimum-enrollment cancellation with refunds, waitlist promotion and drop policy, and attendance tracking gated on participant safety forms.

The API serves two audiences at once. Program coordinators and front-desk staff need an operations surface that keeps the catalog, schedules, contracts, and money mutually consistent as sessions fill, cancel, and complete; household managers need a self-service surface where residency verification, safety clearance, scholarships, registration, and payment compose into one predictable enrollment flow. Because seats are scarce and money moves at nearly every step, the specification leans on three pillars: a registration's fee is computed exactly once and then pinned forever, every mutation carries a version counter for optimistic concurrency, and every cascade — cancellation, waitlist promotion, refund issuance, instructor settlement — follows an exact, replayable rule rather than operator judgment. All temporal rules (windows, deadlines, sweeps) evaluate against a server-side logical clock so that behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `HouseholdManager`, `ProgramCoordinator`, `FrontDeskStaff`, `Instructor`, `ScholarshipReviewer`, and `FinanceOfficer`. A request with a missing or unrecognized `X-User-Role`, or a missing `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED`. Access to each operation is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_UNAUTHORIZED_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `HouseholdManager`, `X-User-ID` is the `id` of the acting `Household`; ownership checks on any resource that references a household compare the resource's foreign-key field to `X-User-ID`. Household accounts are self-service: a `HouseholdManager` creates the household account, and the server-minted household `id` becomes the caller's `X-User-ID` for all subsequent `HouseholdManager` calls. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; an instructor may accept or decline only contracts naming them and may mark attendance only for sessions assigned to them, and an identity mismatch on those paths is rejected with `ERR_UNAUTHORIZED_ROLE`.

The remaining roles carry opaque identities. When `X-User-Role` is `ProgramCoordinator`, `FrontDeskStaff`, `ScholarshipReviewer`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `reviewed_by` or `decided_by` on a scholarship application — but does not compare it to any entity's `id`.

List and read endpoints are role-gated only: the ownership and entity-identity checks above apply solely to the mutation paths that name them, never to reads. A `HouseholdManager` may read any household, list any participants, and list any registrations — reads are not scoped to the caller's own household.

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

Two framework-level rejections share this envelope: a request to an undefined path is rejected with `ERR_NOT_FOUND` at HTTP 404, and a request to a defined path with an unsupported method is rejected with `ERR_NOT_FOUND` at HTTP 405. An unexpected server failure is reported as `ERR_INTERNAL` at HTTP 500; it belongs to no workflow and is therefore absent from the §5 catalogue.

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`; out-of-range integers are clamped rather than rejected — a `limit` below 1 becomes 1 and a `limit` above 100 becomes 100, and a negative `offset` becomes 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. When creation timestamps coincide — common under the logical clock — the tie is broken by insertion order, the earlier-created resource first; resource ids are never consulted for ordering. The same insertion-order fallback resolves any residual tie in the ordered workflows of §3: the waitlist promotion selector (§3.8), the absence replay (§3.9), and both sweep queues (§3.9).

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` plus the number of items returned in this page is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in the system — seasons, programs, rooms, instructors, class sessions, class meetings, instructor contracts, households, participants, safety forms, scholarship applications, registrations, payment transactions, and attendance records — carries a standard set of system-managed fields:

- `id` (string): a unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T10:30:00.123Z`) indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; it refreshes upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource; it starts at 1 when the resource is created.

Both timestamps — and the envelope's `api_request_timestamp` — are stamped from the logical clock of §2.5, never from wall-clock time.

The `version` counter is the backbone of optimistic concurrency (§2.7), and it advances on every mutation, including indirect ones: when a cascade touches a registration, a session counter, a household credit balance, or a season's committed scholarship total, each touched entity independently refreshes `updated_at` and increments `version`.

### 2.5. The Logical Clock

The server evaluates every window, deadline, due date, and expiry rule against a logical clock rather than wall-clock time. At startup, before any clock operation, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `ProgramCoordinator`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; the response echoes the new reading as `current_utc`. The supplied value may be any ISO 8601 datetime — an offset-less value is read as UTC, and a bare `YYYY-MM-DD` date becomes midnight UTC — and a malformed value is rejected with `ERR_INVALID_REQUEST`. The clock may be set to any instant, earlier or later than the current reading; no monotonicity is enforced. The response echoes the supplied `to_iso8601` string verbatim as `current_utc`. Advancing the clock mutates no entity by itself — it simply redefines "now" for every rule in this document. Wherever the narratives below say "now", they mean the current reading of this logical clock.

### 2.6. Monetary Values, Cents, and Rounding

All monetary values in the system are integer counts of cents — fees, budgets, commitments, credits, refunds, and settlements alike. Wherever a calculation produces a fractional cent, the value is rounded half-up to a whole cent, and where a calculation chains multiple multiplicative steps, each step is rounded individually in the order the workflow pins (§3.6 and §3.9); rounding once at the end of a chain is a different, non-conforming algorithm. Monetary values appear in API bodies as plain numbers, never strings.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, both against the version of a class session.

Creating a registration requires a non-optional `expected_class_session_version` field carrying the current `version` of the target session as the client last observed it. If the session's version has advanced since that observation — for example, because another registration has legitimately consumed a seat or a waitlist position in the meantime, which itself bumps the session's version — the client's view of seat availability is stale, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Updating a session's `capacity`, `min_enrollment`, or `enrollment_check_at` is likewise guarded: the request must carry `expected_class_session_version` matching the session's current `version`. Enrollments and waitlist movements change the session's counters and version, so a client reasoning about capacity-versus-enrollment from an older read is acting on stale data; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. On both guarded endpoints, the version check is evaluated after authentication, request well-formedness, resource existence, and generic state legality, and before the domain gates described in §3.

### 2.8. Validation Order and Error Precedence

When a single request would violate several rules, the rejection it receives is determined by a fixed precedence ladder — the check with the highest precedence wins, and its error is the one returned. The ladder runs as follows:

1. Authentication — the headers must be present and name a declared role, else `ERR_UNAUTHENTICATED`.
2. Role authorization and entity-backed identity — the caller's role must appear in the endpoint's role list, and an `Instructor` acting on another instructor's contract or session is rejected here, both as `ERR_UNAUTHORIZED_ROLE`.
3. Request well-formedness — required fields present, types correct, enum members valid, and numeric ranges honored: `capacity` greater than zero, `min_enrollment` at least one and no greater than `capacity`, amounts greater than zero, `approved_pct` one of 25, 50, 75, or 100, `revenue_share_bp` between 0 and 10000 inclusive, `ends_at` later than `starts_at`, `min_age` at least zero and `max_age` at least `min_age`, the season window ordering (`resident_opens_at` no later than `general_opens_at`, in turn no later than `registration_closes_at`), and `end_date` later than `start_date`. Violations are `ERR_INVALID_REQUEST`.
4. Existence — path parameters such as `season_id`, `program_id`, `room_id`, `instructor_id`, `session_id`, `meeting_id`, `contract_id`, `household_id`, `participant_id`, `form_id`, `application_id`, `registration_id`, `payment_id`, and `attendance_id` resolve strictly left to right, and the request is rejected with `ERR_NOT_FOUND` naming the first identifier that does not correspond to an existing resource; body-referenced identifiers must likewise reference existing resources before any business rule is evaluated.
5. Generic state-machine legality — the attempted trigger must be defined for the entity's current state. Publishing an already-published session, dropping an already-dropped registration, verifying an already-verified form, withdrawing a denied application, closing a season before its registration deadline, or completing a session with unfinished meetings are all `ERR_INVALID_STATE`.
6. Optimistic-concurrency staleness — `ERR_STALE_VERSION`, per §2.7.
7. Domain gates and business rules, in the pinned order narrated per workflow in §3 — season gates first, then session-open and operation-specific state gates, then safety rules, then temporal windows, then uniqueness, capacity, and scheduling-conflict constraints, then household-membership ownership and segregation of duties, and finally fiscal rules (exact payment amount, sufficient credit, scholarship budget cap).

The per-endpoint narratives in §3 name the concrete error each rung produces, so §5 needs no trigger column.

### 2.9. Booking Intervals and Conflict Semantics

Room and instructor scheduling both reason about half-open time intervals: an interval includes its start instant and excludes its end instant. Two intervals conflict exactly when each starts strictly before the other ends. For rooms, a meeting's occupancy runs from its `starts_at` until fifteen minutes after its `ends_at` — a fixed turnover buffer — so a new meeting that begins at exactly the instant another meeting's buffered occupancy ends is adjacent, not conflicting. For instructors there is no buffer at all: a meeting occupies exactly its own span, so a new meeting starting at exactly the instant the instructor's other meeting ends is likewise allowed. Both checks consider only meetings whose sessions are in `DRAFT`, `PUBLISHED`, or `ACTIVE`; meetings belonging to `CANCELLED` or `COMPLETED` sessions no longer block anything.

### 2.10. Cascading Consistency and Derived Counters

Several entities carry derived counters that the server maintains rather than accepts as input. A class session's `enrolled_count` is the number of its registrations whose `enrollment_status` is `ENROLLED`, and its `waitlist_count` the number `WAITLISTED`; a season's `scholarship_committed_cents` is the sum of `estimated_commitment_cents` over that season's `APPROVED` scholarship applications; a household's `account_credit_cents` is its refund credit balance, incremented by completed refunds and decremented by credit-funded payments. When a state transition on one entity renders others inconsistent — a session cancellation that strands registrations, a freed seat that belongs to a waitlisted neighbor, a revocation that releases budget — the server reconciles the dependents inside the same operation, without requiring separate client calls. Each entity reconciled in such a cascade is itself mutated: its `updated_at` refreshes and its `version` increments (§2.4).

## 3. Business Logic & Workflows

### 3.1. Building the Seasonal Catalog

Work begins with the **Season**. A `ProgramCoordinator` creates it with a `name` (for example, "Fall 2026"), a `start_date` and an `end_date`, and three registration instants: `resident_opens_at`, when households verified as residents may begin registering; `general_opens_at`, when registration opens to everyone; and `registration_closes_at`, when registration closes for all. The three instants must be non-decreasing in that order — `resident_opens_at` no later than `general_opens_at`, which is no later than `registration_closes_at` — and `end_date` must fall after `start_date`; a season that violates either ordering is rejected at creation with `ERR_INVALID_REQUEST`. Like every date-or-instant input in this API — participant `birth_date` included — `start_date` and `end_date` accept a bare `YYYY-MM-DD` date or a full ISO 8601 instant, are stored and echoed as instants (a bare date becomes midnight UTC), and all age arithmetic compares calendar dates, ignoring time of day. Three policy knobs complete the season: `family_discount_threshold` (the household enrollment count in the season at which the family discount applies; it defaults to 3 and must be at least 2), `family_discount_pct` (the percent taken off after the scholarship step; it defaults to 10 and must lie between 0 and 100 inclusive), and `scholarship_budget_cents` (the season's total scholarship commitment budget; it defaults to 0 and cannot be negative). The server maintains `scholarship_committed_cents` — the sum of commitments across the season's approved applications — starting from zero. A season is born `DRAFT`, moves to `PUBLISHED` when the coordinator publishes it, and finally to `CLOSED`, which is terminal.

Closing a season is allowed only once now has reached `registration_closes_at`; an early close is rejected with `ERR_INVALID_STATE`. Once a season is `CLOSED`, new registrations against any of its sessions are rejected with `ERR_SEASON_CLOSED`, and new catalog content is likewise refused. While a season is still `DRAFT` or `PUBLISHED`, the coordinator may attach **Programs** to it: each program carries the owning `season_id`, a `name` such as "Youth Basketball", a catalog `category` such as "Sports" or "Arts", and an age corridor — `min_age` defaulting to 0 and `max_age` defaulting to 120, with `min_age` at least zero and `max_age` at least `min_age`. Attempting to add a program while its season is neither `DRAFT` nor `PUBLISHED` — which can only mean the season is `CLOSED`, the sole remaining season state — is rejected with `ERR_SEASON_CLOSED`. Programs can be listed, optionally filtered by `season_id`.

**Rooms** and **Instructors** round out the catalog. A room is created with a `name` (say, "Gymnasium A") and a `capacity` that must be greater than zero, and is born `ACTIVE`. The coordinator may toggle a room between `ACTIVE` and `MAINTENANCE`; a patch naming the status the room already holds is not a toggle and is rejected with `ERR_INVALID_STATE`. While a room is in `MAINTENANCE`, scheduling a new meeting into it or re-assigning an existing meeting into it is rejected with `ERR_ROOM_UNAVAILABLE`, though meetings already placed there are left untouched. An instructor record is simply a `full_name` and a contact `email`.

### 3.2. Sessions, Meetings, and Room Assignment

A **ClassSession** is the sellable unit of a program. The coordinator creates one in `DRAFT` with the `program_id` it delivers, the `instructor_id` assigned to teach it, a `title` such as "Youth Basketball — Tue/Thu 6pm", a `capacity` (the maximum number of coexisting `ENROLLED` registrations at any moment, and greater than zero), a `min_enrollment` (at least one and no greater than `capacity`), resident and non-resident pricing via `fee_resident_cents` and `fee_nonresident_cents` (both non-negative), and an `enrollment_check_at` instant at which the season sweep will judge whether the session has attracted enough enrollment to run. Session creation is permitted only while the owning season is `DRAFT` or `PUBLISHED`, under the same season gates as program creation. Sessions can be listed with optional `program_id`, `instructor_id`, and `status` filters.

While a session remains `DRAFT` or `PUBLISHED`, the coordinator may patch its `capacity`, `min_enrollment`, or `enrollment_check_at`. The patch is OCC-guarded per §2.7 — it must carry `expected_class_session_version`, and a stale value is rejected with `ERR_STALE_VERSION` before any domain rule is consulted — and the new `capacity` may never drop below the session's current `enrolled_count`; a patch that would strand existing enrollees is rejected with `ERR_CAPACITY_BELOW_ENROLLED`. Each supplied value must satisfy its creation-time range (`capacity` greater than zero, `min_enrollment` at least one), and a patch that supplies only one of `capacity` and `min_enrollment` is validated against the stored value of the other — the merged pair must keep `min_enrollment` no greater than `capacity`, else `ERR_INVALID_REQUEST`; because the merged pair needs the stored record, this check runs after existence resolution and before state legality. A patch that changes no field still succeeds — bumping `version` once — provided every guard passes. Among the patch's own checks, generic state legality comes first, then staleness, then the capacity floor.

Each session meets through one or more **ClassMeetings**, created with the `session_id`, the assigned `room_id`, and a `starts_at`/`ends_at` pair with `ends_at` strictly later than `starts_at`. Meeting creation is season-gated like session creation — and gated only by the season: the session's own status does not restrict adding a meeting — and then runs four scheduling checks in a fixed order: first the room must be large enough — the room's `capacity` at least the session's `capacity`, with equality allowed — else `ERR_ROOM_CAPACITY_INSUFFICIENT`; second the room must be `ACTIVE`, else `ERR_ROOM_UNAVAILABLE`; third the buffered room-overlap check of §2.9 runs against every other meeting in the same room whose session is non-terminal, rejecting collisions with `ERR_ROOM_CONFLICT`; fourth the unbuffered instructor-overlap check runs against meetings of other non-terminal sessions assigned to the same instructor, rejecting collisions with `ERR_INSTRUCTOR_DOUBLE_BOOKED`. A meeting may be re-assigned or rescheduled — new `room_id`, `starts_at`, or `ends_at` — only while its session is `DRAFT` or `PUBLISHED`, and the patch re-runs the capacity, availability, and both overlap checks with the new values, excluding the meeting itself from its own candidate sets; unsupplied fields keep their stored values, and the `ends_at`-later-than-`starts_at` rule is re-validated on the merged pair (after the meeting and any newly referenced room have been resolved). Meetings can be listed, optionally filtered by `session_id` and `room_id`.

### 3.3. Instructor Contracts and Session Publication

No session opens for registration until its instructor is under contract. The coordinator offers an **InstructorContract** naming the `session_id` and the `instructor_id` — which must equal the session's assigned instructor, on pain of `ERR_CONTRACT_INSTRUCTOR_MISMATCH` — together with four commercial terms: `revenue_share_bp`, the instructor's share of each counted registration's net paid amount expressed in basis points between 0 and 10000 inclusive; `guarantee_min_cents`, a settlement floor; `cancellation_guarantee_cents`, the flat payout owed if an accepted contract is terminated by session cancellation; and `settlement_basis`, either `ENROLLMENT_BASIS` or `ATTENDANCE_BASIS`, selecting which headcount the eventual settlement pays on. Both `guarantee_min_cents` and `cancellation_guarantee_cents` must be non-negative, zero included. Offering a contract is not season-gated: it is permitted whatever the owning season's state. A session may have at most one contract in `OFFERED` or `ACCEPTED`; a second offer while one is outstanding is rejected with `ERR_DUPLICATE_CONTRACT`. Of the two duplicate/mismatch guards, the duplicate guard is evaluated first.

A contract is born `OFFERED`. The named instructor — and only that instructor, by entity-backed identity — may accept it, moving it to `ACCEPTED`, provided the session is still `DRAFT` or `PUBLISHED`; accepting under any other session state is `ERR_INVALID_STATE`, and a different instructor attempting the accept is `ERR_UNAUTHORIZED_ROLE`. The instructor may instead decline, moving the contract to `DECLINED` with `payout_cents` recorded as zero. While a contract is `OFFERED` or `ACCEPTED` its `payout_cents`, `settlement_headcount`, and `settlement_amount_cents` remain null; the terminal states fix them — zero for `VOID` and `DECLINED`, the cancellation guarantee for `TERMINATED`, and the computed settlement for `SETTLED`.

Publishing a session — moving it from `DRAFT` to `PUBLISHED` — is the coordinator's final assembly step, and it enforces three preconditions in a pinned order. The owning season must be `PUBLISHED`, else `ERR_SEASON_NOT_PUBLISHED`. An `ACCEPTED` contract must exist for the session and its assigned instructor, else `ERR_CONTRACT_NOT_ACCEPTED`. The session must have at least one class meeting, else `ERR_NO_MEETINGS`. A session failing both the contract and meeting requirements is therefore reported as `ERR_CONTRACT_NOT_ACCEPTED`. Publication is what makes a session visible to the registration flow of §3.6.

### 3.4. Households, Participants, and Safety Clearance

A **Household** account is created self-service by a `HouseholdManager` with an `account_name`; the minted household `id` is thenceforth the caller's `X-User-ID`. The household's `residency_status` begins `PENDING`, and its `account_credit_cents` balance begins at zero. A `FrontDeskStaff` operator verifies residency by posting a `residency_status` of `RESIDENT` or `NONRESIDENT`; re-verification is allowed in both directions, so a household can move from `RESIDENT` to `NONRESIDENT` or back as circumstances change. Re-verification never disturbs existing registrations: each registration's fee basis and charged fee are pinned at creation (§3.6), and only future registrations observe the new status.

**Participants** are the household's members. A `HouseholdManager` adds one with the owning `household_id`, a `full_name`, and a `birth_date`; the `household_id` must be the caller's own household, else the request is rejected with `ERR_NOT_HOUSEHOLD_MEMBER`. A participant's age for eligibility purposes is measured as whole years completed by the season's `start_date` (§3.6). Participants can be listed, optionally filtered by `household_id`.

Before any participant sets foot in a meeting, the household files a **SafetyForm** for the pairing of that participant and the season, carrying `emergency_contact_name`, `emergency_contact_phone`, an optional `medical_notes` free-text defaulting to empty, and a `signer_name`. Signature rules depend on age measured at the season's `start_date`: a minor — under eighteen — must be signed by someone other than the participant, and a self-signed minor's form is rejected with `ERR_GUARDIAN_SIGNATURE_REQUIRED`; an adult — eighteen or older — must self-sign, and a form signed by anyone else is rejected with `ERR_SELF_SIGNATURE_REQUIRED`. At most one form per participant-and-season may be live in `SUBMITTED` or `VERIFIED`; a second submission while one is live is rejected with `ERR_DUPLICATE_SAFETY_FORM`. The signature rules are evaluated before the duplicate-form guard, and the household-membership check — the participant must belong to the caller's household, else `ERR_NOT_HOUSEHOLD_MEMBER` — comes after both.

A form is born `SUBMITTED`. `FrontDeskStaff` then verifies it, moving it to `VERIFIED`, or rejects it, moving it to `REJECTED`, optionally carrying a `reason` in the request, which is accepted but not persisted on the form; both outcomes are terminal. Rejection reopens the slot: once a form is `REJECTED`, the uniqueness gate no longer blocks, and a fresh form for the same participant and season may be submitted. Forms can be listed with optional `participant_id`, `season_id`, and `status` filters. Only a `VERIFIED` form clears the participant for attendance marking (§3.9).

### 3.5. Scholarship Applications and the Review Cycle

A household seeking fee relief files a **ScholarshipApplication** for a season with its `household_id` and `season_id`, a `household_size` of at least one, a non-negative `annual_income_cents`, and an optional free-text `statement` that defaults to empty. The applicant household must be the caller's own, else `ERR_NOT_HOUSEHOLD_MEMBER`, and at most one application per household-and-season may be live in any of `SUBMITTED`, `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, `RESUBMITTED`, or `APPROVED`; a second filing while one is live is rejected with `ERR_DUPLICATE_SCHOLARSHIP_APPLICATION`, a guard evaluated before the ownership check. Applications can be listed with optional `household_id`, `season_id`, and `status` filters.

Review is a `ScholarshipReviewer` workflow with a segregation-of-duties spine. A reviewer claims a `SUBMITTED` or `RESUBMITTED` application by starting review, moving it to `UNDER_REVIEW` and stamping `reviewed_by` with their own `X-User-ID`; a later start-review after resubmission overwrites the previous `reviewed_by`, and the segregation check always compares against this latest value. From `UNDER_REVIEW` the reviewer may request more information, moving the application to `MORE_INFO_REQUESTED` and recording the payload's `info_request_note` describing what to supply. The household then resubmits with an updated `statement` — the caller must belong to the applicant household, else `ERR_NOT_HOUSEHOLD_MEMBER` — returning the application to `RESUBMITTED`, from which a fresh start-review cycles it back to `UNDER_REVIEW`.

Two decisions end the review. Approval moves the application to `APPROVED` and is fenced by two checks, evaluated state legality first, then segregation, then budget: the approving reviewer's `X-User-ID` must differ from `reviewed_by` — the same person may not both claim and approve — else `ERR_SEGREGATION_OF_DUTIES`; and the season's budget must absorb the commitment, meaning `scholarship_committed_cents` plus the payload's `estimated_commitment_cents` (non-negative, zero allowed) must not exceed the season's `scholarship_budget_cents`, with a commitment landing exactly on the remaining budget allowed, else `ERR_SCHOLARSHIP_BUDGET_EXCEEDED`. A successful approval stamps the payload's `approved_pct` — one of `25`, `50`, `75`, or `100` — and `estimated_commitment_cents` onto the application, records the caller as `decided_by`, and adds the commitment to the season's `scholarship_committed_cents`, bumping the season's `version`. Denial moves the application to `DENIED` and records `decided_by` as well, optionally carrying a `reason` in the request, which — like the rejection reason on a safety form — is accepted but not persisted; denial is deliberately not subject to segregation of duties. Before any decision, the household may withdraw from `SUBMITTED`, `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `RESUBMITTED`, moving the application to `WITHDRAWN` — again only for its own household.

An approval is not necessarily permanent. A `FinanceOfficer` may revoke an `APPROVED` application, moving it to `REVOKED`; the revocation subtracts the application's `estimated_commitment_cents` from the season's `scholarship_committed_cents` as a compensating reversal, bumping the season's `version` once more. Revocation is deliberately non-retroactive for money already charged: existing registrations keep their pinned `scholarship_pct_applied` and `fee_charged_cents`, while future registrations by that household in that season receive a scholarship percent of zero.

### 3.6. Registration: Windows, Eligibility, and the Pinned Fee

Registration is the act of placing a participant into a session, performed by the household's own `HouseholdManager` or by `FrontDeskStaff` on the household's behalf, via a payload naming the `session_id`, the `participant_id`, and the OCC token `expected_class_session_version`. The request runs a long gauntlet whose internal order is pinned: after the generic rungs of §2.8 and the stale-version check of §2.7, the season gates fire first — a season still `DRAFT` rejects with `ERR_SEASON_NOT_PUBLISHED`, a season already `CLOSED` with `ERR_SEASON_CLOSED` — then the session itself must be `PUBLISHED` or `ACTIVE`, else `ERR_SESSION_NOT_OPEN`. Next come the temporal windows in their chronological logic. Before `resident_opens_at` nobody may register, and the attempt is rejected with `ERR_REGISTRATION_WINDOW_NOT_OPEN`. During the resident-priority window — from `resident_opens_at` up to but not including `general_opens_at` — only households whose `residency_status` is `RESIDENT` may register; `NONRESIDENT` and still-`PENDING` households are turned away with `ERR_RESIDENT_PRIORITY_WINDOW`. Once now reaches `registration_closes_at` registration is over — equality means closed — and the attempt is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`. After the windows, the duplicate guard fires: at most one registration per participant-and-session may be live in `ENROLLED` or `WAITLISTED`, else `ERR_DUPLICATE_REGISTRATION`. Then age eligibility: the participant's age is the whole years completed between `birth_date` and the season's `start_date`, a birthday falling exactly on `start_date` counting as reached, and the age must be at least the program's `min_age` and at most its `max_age`, both bounds inclusive, else `ERR_AGE_INELIGIBLE`. Finally, a `HouseholdManager` caller must own the participant's household, else `ERR_NOT_HOUSEHOLD_MEMBER`; `FrontDeskStaff` is exempt from that last check.

A registration that clears the gauntlet lands in one of two places. If the session's `enrolled_count` has already reached `capacity`, the newcomer is `WAITLISTED` and its `waitlisted_at` records the instant; otherwise it is `ENROLLED`. Either way the session's corresponding counter increases by one and the session's `version` bumps — which is precisely why the create carries the OCC token. The registration denormalizes its `household_id` from the participant's household at creation and never changes it thereafter.

The fee is computed exactly once at creation and stored in `fee_charged_cents`, never recomputed afterwards — later residency changes, later scholarship approvals or revocations, and later drops of siblings all leave it untouched. The base is the session's `fee_resident_cents` when the household's `residency_status` is `RESIDENT` at the creation instant, and `fee_nonresident_cents` otherwise, a still-`PENDING` household paying the non-resident rate; that basis is snapshotted onto the registration as `residency_at_registration`, `RESIDENT` if and only if the household was `RESIDENT` at that instant. The scholarship step applies first: when the household holds an `APPROVED` application for the season, its `approved_pct` — locked onto the registration as `scholarship_pct_applied`, zero when no such application exists — is deducted by multiplying the base by one hundred minus that percent and dividing by one hundred, rounding half-up to a whole cent. The family step applies second: when the family discount evaluates in this registration's favor, the rounded intermediate is multiplied by one hundred minus the season's `family_discount_pct` and divided by one hundred, again rounding half-up to a whole cent. The two roundings are pinned in this order — scholarship first, family second.

The family discount itself is a pinned counting rule evaluated at creation. Count the household's existing registrations in the same season whose `enrollment_status` is `ENROLLED` — `WAITLISTED` siblings do not count — then add one for the registration being created; if that total reaches the season's `family_discount_threshold`, meeting the threshold exactly qualifies, and `family_discount_applied` is recorded true, otherwise false. There is no retroactivity: once recorded, `family_discount_applied` and `fee_charged_cents` never change.

Payment expectations attach immediately, on a second state axis stored as the registration's `payment_status` — parallel to and independent of `enrollment_status`, evolving on its own save for the pinned interaction points at creation, promotion, and terminal resolution. A registration landing `ENROLLED` with a fee greater than zero is born with `payment_status` `PENDING` and a `payment_due_at` deadline seventy-two hours — three days — after its creation. One whose pinned fee is zero moves straight from `PENDING` to `WAIVED`, with no deadline. A `WAITLISTED` registration keeps `payment_status` `PENDING` with `payment_due_at` null while it waits. The registration also carries `net_paid_cents` and `refund_total_cents` starting at zero, a `drop_reason` that stays null while the registration is active, a `promoted_at` that stays null until a waitlist promotion, and a `consecutive_absences` counter starting at zero (§3.9). Registrations can be listed with optional `session_id`, `participant_id`, `household_id`, and `enrollment_status` filters.

### 3.7. Payment and the Household Credit Ledger

Paying a registration is a single-shot affair: the payer — the owning `HouseholdManager`, or `FrontDeskStaff` on their behalf — submits `amount_cents` and a `method` — one of `EXTERNAL` or `ACCOUNT_CREDIT` — and a `PaymentTransaction` ledger entry is created. Every ledger entry is bound to its `registration_id` and carries a `type` — `CHARGE` when the participant pays, `REFUND` when the center returns money — and every `CHARGE` is born `COMPLETED`, while only `REFUND` entries may ever be born `PENDING`. The checks run in a fixed order: the registration must be `ENROLLED` on the enrollment axis and `PENDING` on the payment axis, else `ERR_PAYMENT_NOT_ALLOWED` — a `WAITLISTED` registration cannot pay, and a second payment on a `PAID` registration fails here as well; then household membership for `HouseholdManager` callers, else `ERR_NOT_HOUSEHOLD_MEMBER`; then the amount must equal the pinned `fee_charged_cents` exactly, with no partial payments and no overpayment, else `ERR_INCORRECT_AMOUNT`; and finally, when `method` is `ACCOUNT_CREDIT`, the household's `account_credit_cents` must cover the amount, else `ERR_INSUFFICIENT_CREDIT`. A successful payment creates a `CHARGE` transaction born `COMPLETED`, moves the payment axis to `PAID`, adds the amount to the registration's `net_paid_cents`, and clears `payment_due_at` to null. An `ACCOUNT_CREDIT` charge additionally subtracts the amount from the household's `account_credit_cents`, bumping the household's `version`; an `EXTERNAL` charge touches no credit balance.

Every refund the center owes flows back as household credit. A `REFUND` transaction always carries `method` `ACCOUNT_CREDIT`, and its life depends on size: amounts below one hundred dollars — 10000 cents — are auto-approved and born `COMPLETED`, while amounts of one hundred dollars or more are born `PENDING` and wait for a `FinanceOfficer` to approve the refund. Approval requires the transaction to be a `REFUND` still `PENDING`, else `ERR_REFUND_NOT_PENDING`; it moves the transaction to `COMPLETED`, adds the amount to the household's `account_credit_cents` and to the registration's `refund_total_cents`, and advances the registration's payment axis from `REFUND_PENDING` to `REFUNDED`. On the registration, `refund_total_cents` is the running total of refund money returned, growing by a refund's `amount_cents` at the moment that refund completes — immediately for auto-approved small refunds, or upon Finance approval for large ones. All payment entries can be listed, optionally filtered by `registration_id`; the default chronological ordering by `created_at` ascending guarantees a `CHARGE` precedes its `REFUND`.

### 3.8. Drops, Refunds, and Waitlist Promotion

A household may pull a participant out at any time while the session is still open. The drop is requested by the owning `HouseholdManager` or by `FrontDeskStaff`; the session must be `PUBLISHED` or `ACTIVE`, else `ERR_SESSION_NOT_OPEN`, and a `HouseholdManager` dropping outside their own household is rejected with `ERR_NOT_HOUSEHOLD_MEMBER`. What happens next depends on which side of the waitlist the registration sits on.

Dropping a `WAITLISTED` registration is quiet: it moves to `DROPPED` with `drop_reason` `VOLUNTARY`, a `PENDING` payment axis is voided to `VOID` while `WAIVED` is left alone, no refund ever issues because nothing was collectible while waitlisted, the session's `waitlist_count` decreases by one, and no promotion runs — no seat was occupied. Voiding an axis — here and everywhere it occurs — never clears `payment_due_at`; the deadline value is simply moot once the axis is `VOID`.

Dropping an `ENROLLED` registration fires the refund rule and then the promotion rule. The voluntary-drop refund is tiered by how much of the session has already transpired at the drop instant. A meeting counts as held when its `starts_at` is at or before now, and dropping at exactly a meeting's start time counts that meeting as held. If no meeting has been held, the refund is the full `net_paid_cents`. Otherwise, take the halfway point of the session — its total meeting count divided by two, rounded down to a whole number: when the number of meetings held is between one and that halfway point inclusive, the refund is one half of `net_paid_cents`, rounded half-up to a whole cent; when the number held exceeds the halfway point, the refund is zero. Issuance then follows the ledger rules of §3.7: a refund greater than zero creates a `REFUND` transaction — `PENDING` at or above the one-hundred-dollar review threshold, moving the payment axis from `PAID` to `REFUND_PENDING`, otherwise `COMPLETED`, moving `PAID` to `REFUNDED` and crediting the household — while a zero refund creates nothing and leaves `PAID` untouched, and a never-paid `PENDING` registration simply voids to `VOID`.

The freed seat is offered immediately. The waitlist promotion selector gathers the session's `WAITLISTED` registrations — only while the session is `PUBLISHED` or `ACTIVE` — ranks them by `waitlisted_at` ascending with `created_at` ascending as the tie-break and insertion order as the final fallback (§2.3), and never consults the registration `id` for ordering. If no candidate exists, the seat simply stays open. Otherwise the first-ranked registration is promoted to `ENROLLED` with `promoted_at` set to now — `waitlisted_at` is left in place as history: when its pinned fee is greater than zero its `payment_due_at` becomes forty-eight hours — two days — after `promoted_at` and its payment axis stays `PENDING`; when the pinned fee is zero its payment axis moves from `PENDING` to `WAIVED` with no deadline. The session's `waitlist_count` decreases by one and its `enrolled_count` climbs back by one, so a voluntary drop nets out to a decrement followed by an increment, each bumping the session's `version`.

The same machinery serves harsher triggers. A no-show drop (§3.9) moves an `ENROLLED` registration to `DROPPED` with `drop_reason` `NO_SHOW`, and its refund is always zero — a forfeit regardless of timing — so `PAID` stays `PAID`, an unpaid `PENDING` voids, and no transaction is created; the seat then frees and the promotion selector runs exactly as after a voluntary drop.

### 3.9. Attendance, Session Completion, and the Season Sweep

Once meetings begin, attendance is marked per meeting and per registration by the session's own `Instructor` or by `FrontDeskStaff`, recording a `meeting_id`, a `registration_id` that must belong to the meeting's session — one naming a registration of a different session is rejected with `ERR_NOT_FOUND`, exactly as if it did not resolve here — and a `status` of `PRESENT`, `ABSENT`, or `EXCUSED`. Four gates guard the mark, in pinned order: the registration must be `ENROLLED`, else `ERR_REGISTRATION_NOT_ENROLLED`; a `VERIFIED` safety form must exist for the participant in the session's season, else `ERR_SAFETY_FORM_REQUIRED`; the meeting must have started — now at or after its `starts_at` — else `ERR_ATTENDANCE_TOO_EARLY`; and at most one record may exist per meeting-and-registration, else `ERR_DUPLICATE_ATTENDANCE`. Mark creation is not gated on the session's own status — the four gates are exhaustive. Marks are correctable while the session is `PUBLISHED` or `ACTIVE` — any mark may be changed to any other, and a correction under any other session state is `ERR_INVALID_STATE`. Records can be listed, optionally filtered by `meeting_id` and `registration_id`.

Every creation and every correction replays the affected registration's absence run from scratch. The replay walks the registration's records on meetings already started — meeting `starts_at` at or before now — ordered by meeting start ascending with the record's own `created_at` breaking ties: a `PRESENT` mark resets the running counter to zero, an `ABSENT` mark adds one, and an `EXCUSED` mark leaves the counter unchanged, neither incrementing nor resetting. The final count is stored as `consecutive_absences`. When the counter reaches three — exactly three consecutive unexcused absences is enough — and the registration is still `ENROLLED`, the no-show drop of §3.8 fires with its forfeit refund and its waitlist promotion. A drop that has fired is final: later corrections may lower the counter, but they never resurrect a dropped registration.

Completion is the coordinator's closing act on a session. It is allowed only from `ACTIVE` and only once every meeting of the session has ended — each meeting's `ends_at` at or before now — else `ERR_INVALID_STATE`. Completion settles the instructor: the session's `ACCEPTED` contract moves to `SETTLED`; a contract still `OFFERED` is voided with `payout_cents` zero; a `DECLINED` one is untouched. The settlement first determines the counted registrations. Under `ENROLLMENT_BASIS`, every registration still `ENROLLED` at completion counts. Under `ATTENDANCE_BASIS`, a registration counts only when it is still `ENROLLED` at completion and its attendance percentage reaches the qualifying mark of fifty percent — a percentage of exactly fifty qualifies; the percentage is zero when no meeting of the session has been held, and otherwise one hundred times the registration's `PRESENT` marks on meetings already held, divided by the number of meetings held. The comparison is exact, with no rounding of the percentage: a registration qualifies exactly when twice its `PRESENT`-on-held-meetings count is greater than or equal to the number of meetings held. Each counted registration then contributes a line equal to its `net_paid_cents` multiplied by the contract's `revenue_share_bp` and divided by ten thousand, rounded half-up to a whole cent — each line rounded first, then the rounded lines summed; summing raw fractions and rounding once is a different, non-conforming algorithm. `settlement_headcount` records the number of counted registrations, and `settlement_amount_cents` is the greater of the contract's `guarantee_min_cents` and the summed subtotal; `payout_cents` equals `settlement_amount_cents`. Registrations still `WAITLISTED` at completion are moved to `CANCELLED` with `drop_reason` `ADMIN`, their `PENDING` payment axes voided and `WAIVED` untouched; registrations `ENROLLED` at completion simply remain `ENROLLED` as history, and any later drop attempt is rejected with `ERR_SESSION_NOT_OPEN`.

Cancellation is the mirror image. The coordinator may cancel a `PUBLISHED` or `ACTIVE` session outright, and the season sweep may cancel a `PUBLISHED` session that fails its enrollment check; both paths land on `CANCELLED`, setting `cancellation_reason` to `ADMIN` for a manual cancel or `LOW_ENROLLMENT` for a sweep cancel, and both run the same full cascade. Every `ENROLLED` registration moves to `CANCELLED` with `drop_reason` matching the session's reason, and each runs the cancellation variant of the refund rule: a full one hundred percent of `net_paid_cents`, regardless of timing, issued through the standard ledger path — `PENDING` and `REFUND_PENDING` at or above the review threshold, auto-`COMPLETED` and `REFUNDED` below it with the household credited, a never-paid `PENDING` axis voided, and `WAIVED` left alone. Every `WAITLISTED` registration likewise moves to `CANCELLED` with the same `drop_reason`, its `PENDING` axis voided and `WAIVED` untouched, and no promotion runs because the session is terminal. The contract follows: `ACCEPTED` moves to `TERMINATED` with `payout_cents` equal to `cancellation_guarantee_cents`, `OFFERED` moves to `VOID` with `payout_cents` zero, and `DECLINED` is unchanged. Finally, the cancelled session's meetings leave the room and instructor conflict candidate sets — a cancelled session no longer blocks scheduling. Each registration, household, contract, and session touched by the cascade refreshes `updated_at` and increments `version`.

The season sweep is the coordinator's ops-run checkpoint, and it executes two steps in a pinned order. The sweep itself is not state-gated: it may be run against a `DRAFT`, `PUBLISHED`, or `CLOSED` season alike — step one runs regardless, while step two simply finds no eligible sessions unless the season is `PUBLISHED`. Step one expires stalled payments: every registration in the season that is `ENROLLED` with a `PENDING` payment axis whose `payment_due_at` is set and at or before now moves to `EXPIRED` with `drop_reason` `PAYMENT_TIMEOUT`; its payment axis voids — nothing was paid, so there is nothing to refund — the session's `enrolled_count` decreases by one, and the promotion selector runs immediately for that session before the next expiry is processed. Expiries are processed in `payment_due_at` ascending order, ties broken by `created_at` ascending, and because an in-sweep promotion sets the new enrollee's deadline forty-eight hours ahead, a registration promoted during the sweep never expires within the same sweep. Step two evaluates minimum enrollment for every session of a `PUBLISHED` season whose own status is still `PUBLISHED` and whose `enrollment_check_at` is at or before now, processed in `enrollment_check_at` ascending order with `created_at` ascending tie-breaks: a session whose `enrolled_count` reaches its `min_enrollment` — equality passes — activates from `PUBLISHED` to `ACTIVE`, while one that falls short is cancelled with `cancellation_reason` `LOW_ENROLLMENT` and the full cascade above. The sweep responds with a summary of the run: `activated_session_ids`, `cancelled_session_ids`, `expired_registration_ids`, and `promoted_registration_ids`, and every mutated entity's `version` increments.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new distinct resources to a collection return a `201 Created` status code — this includes the payment operation, which creates a `PaymentTransaction` ledger entry. Operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a routing summary only; the request payloads, computed fields, cascades, and rejection rules for each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramCoordinator |
| POST | `/seasons` | Create a season catalog in `DRAFT` | ProgramCoordinator |
| GET | `/seasons/{season_id}` | Read one season | All roles |
| POST | `/seasons/{season_id}/publish` | Publish a season (`DRAFT` → `PUBLISHED`) | ProgramCoordinator |
| POST | `/seasons/{season_id}/close` | Close a season (`PUBLISHED` → `CLOSED`) | ProgramCoordinator |
| POST | `/seasons/{season_id}/sweeps` | Run the season sweep (payment timeouts, then enrollment checks) | ProgramCoordinator |
| POST | `/programs` | Create a program inside a season | ProgramCoordinator |
| GET | `/programs` | List programs, optionally filtered by season | All roles |
| GET | `/programs/{program_id}` | Read one program | All roles |
| POST | `/rooms` | Create a room (status `ACTIVE`) | ProgramCoordinator |
| GET | `/rooms/{room_id}` | Read one room | All roles |
| PATCH | `/rooms/{room_id}` | Toggle room status between `ACTIVE` and `MAINTENANCE` | ProgramCoordinator |
| POST | `/instructors` | Create an instructor | ProgramCoordinator |
| GET | `/instructors/{instructor_id}` | Read one instructor | All roles |
| POST | `/class-sessions` | Create a class session in `DRAFT` | ProgramCoordinator |
| GET | `/class-sessions` | List class sessions with optional filters | All roles |
| GET | `/class-sessions/{session_id}` | Read one class session | All roles |
| PATCH | `/class-sessions/{session_id}` | Update capacity, minimum enrollment, or check instant (OCC-guarded) | ProgramCoordinator |
| POST | `/class-sessions/{session_id}/publish` | Publish a session (`DRAFT` → `PUBLISHED`) | ProgramCoordinator |
| POST | `/class-sessions/{session_id}/cancel` | Cancel a session with full cascade (reason `ADMIN`) | ProgramCoordinator |
| POST | `/class-sessions/{session_id}/complete` | Complete a session and settle its contract | ProgramCoordinator |
| POST | `/class-meetings` | Add a meeting with room assignment and conflict checks | ProgramCoordinator |
| GET | `/class-meetings` | List meetings, optionally filtered by session and/or room | All roles |
| GET | `/class-meetings/{meeting_id}` | Read one meeting | All roles |
| PATCH | `/class-meetings/{meeting_id}` | Re-assign or reschedule a meeting; re-runs all checks | ProgramCoordinator |
| POST | `/instructor-contracts` | Offer a contract (`OFFERED`) for a session | ProgramCoordinator |
| GET | `/instructor-contracts` | List contracts, optionally filtered by session and/or instructor | All roles |
| GET | `/instructor-contracts/{contract_id}` | Read one contract | All roles |
| POST | `/instructor-contracts/{contract_id}/accept` | Instructor accepts own contract (`OFFERED` → `ACCEPTED`) | Instructor |
| POST | `/instructor-contracts/{contract_id}/decline` | Instructor declines own contract (`OFFERED` → `DECLINED`) | Instructor |
| POST | `/households` | Self-service household account creation | HouseholdManager |
| GET | `/households/{household_id}` | Read one household, including its credit balance | HouseholdManager, FrontDeskStaff, ProgramCoordinator, FinanceOfficer |
| POST | `/households/{household_id}/verify-residency` | Verify or re-verify household residency | FrontDeskStaff |
| POST | `/participants` | Add a participant to the caller's household | HouseholdManager |
| GET | `/participants` | List participants, optionally filtered by household | HouseholdManager, FrontDeskStaff, ProgramCoordinator |
| GET | `/participants/{participant_id}` | Read one participant | HouseholdManager, FrontDeskStaff, ProgramCoordinator |
| POST | `/safety-forms` | Submit a safety form for a participant and season | HouseholdManager |
| GET | `/safety-forms` | List safety forms with optional filters | HouseholdManager, FrontDeskStaff, ProgramCoordinator |
| GET | `/safety-forms/{form_id}` | Read one safety form | HouseholdManager, FrontDeskStaff, ProgramCoordinator |
| POST | `/safety-forms/{form_id}/verify` | Verify a `SUBMITTED` form | FrontDeskStaff |
| POST | `/safety-forms/{form_id}/reject` | Reject a `SUBMITTED` form | FrontDeskStaff |
| POST | `/scholarship-applications` | Submit a scholarship application for a household and season | HouseholdManager |
| GET | `/scholarship-applications` | List scholarship applications with optional filters | HouseholdManager, ScholarshipReviewer, FinanceOfficer, ProgramCoordinator |
| GET | `/scholarship-applications/{application_id}` | Read one scholarship application | HouseholdManager, ScholarshipReviewer, FinanceOfficer, ProgramCoordinator |
| POST | `/scholarship-applications/{application_id}/start-review` | Claim an application for review | ScholarshipReviewer |
| POST | `/scholarship-applications/{application_id}/request-info` | Request more information from the applicant | ScholarshipReviewer |
| POST | `/scholarship-applications/{application_id}/resubmit` | Resubmit with an updated statement | HouseholdManager |
| POST | `/scholarship-applications/{application_id}/approve` | Approve with discount percent and budget commitment | ScholarshipReviewer |
| POST | `/scholarship-applications/{application_id}/deny` | Deny the application | ScholarshipReviewer |
| POST | `/scholarship-applications/{application_id}/withdraw` | Withdraw a pre-decision application | HouseholdManager |
| POST | `/scholarship-applications/{application_id}/revoke` | Revoke an approved application and reverse its commitment | FinanceOfficer |
| POST | `/registrations` | Register a participant into a session (OCC-guarded; fee pinned) | HouseholdManager, FrontDeskStaff |
| GET | `/registrations` | List registrations with optional filters | HouseholdManager, FrontDeskStaff, ProgramCoordinator, FinanceOfficer |
| GET | `/registrations/{registration_id}` | Read one registration | HouseholdManager, FrontDeskStaff, ProgramCoordinator, FinanceOfficer |
| POST | `/registrations/{registration_id}/drop` | Voluntary drop with refund and promotion cascade | HouseholdManager, FrontDeskStaff |
| POST | `/registrations/{registration_id}/payment` | Pay the pinned fee in full | HouseholdManager, FrontDeskStaff |
| GET | `/payments` | List payment transactions, optionally filtered by registration | HouseholdManager, FrontDeskStaff, ProgramCoordinator, FinanceOfficer |
| GET | `/payments/{payment_id}` | Read one payment transaction | HouseholdManager, FrontDeskStaff, ProgramCoordinator, FinanceOfficer |
| POST | `/payments/{payment_id}/approve-refund` | Approve a `PENDING` refund and credit the household | FinanceOfficer |
| POST | `/attendance-records` | Mark attendance for a registration at a meeting | Instructor, FrontDeskStaff |
| GET | `/attendance-records` | List attendance records with optional filters | Instructor, FrontDeskStaff, ProgramCoordinator |
| GET | `/attendance-records/{attendance_id}` | Read one attendance record | Instructor, FrontDeskStaff, ProgramCoordinator |
| PATCH | `/attendance-records/{attendance_id}` | Correct an attendance mark | Instructor, FrontDeskStaff |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEASON_NOT_PUBLISHED` | 409 |
| `ERR_SEASON_CLOSED` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_REGISTRATION_NOT_ENROLLED` | 409 |
| `ERR_PAYMENT_NOT_ALLOWED` | 409 |
| `ERR_REFUND_NOT_PENDING` | 409 |
| `ERR_CONTRACT_NOT_ACCEPTED` | 409 |
| `ERR_SAFETY_FORM_REQUIRED` | 422 |
| `ERR_GUARDIAN_SIGNATURE_REQUIRED` | 422 |
| `ERR_SELF_SIGNATURE_REQUIRED` | 422 |
| `ERR_REGISTRATION_WINDOW_NOT_OPEN` | 422 |
| `ERR_RESIDENT_PRIORITY_WINDOW` | 422 |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 422 |
| `ERR_ATTENDANCE_TOO_EARLY` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_AGE_INELIGIBLE` | 422 |
| `ERR_ROOM_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 |
| `ERR_CAPACITY_BELOW_ENROLLED` | 409 |
| `ERR_NO_MEETINGS` | 422 |
| `ERR_DUPLICATE_SAFETY_FORM` | 409 |
| `ERR_DUPLICATE_SCHOLARSHIP_APPLICATION` | 409 |
| `ERR_DUPLICATE_ATTENDANCE` | 409 |
| `ERR_DUPLICATE_CONTRACT` | 409 |
| `ERR_CONTRACT_INSTRUCTOR_MISMATCH` | 422 |
| `ERR_NOT_HOUSEHOLD_MEMBER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INCORRECT_AMOUNT` | 422 |
| `ERR_INSUFFICIENT_CREDIT` | 422 |
| `ERR_SCHOLARSHIP_BUDGET_EXCEEDED` | 422 |
