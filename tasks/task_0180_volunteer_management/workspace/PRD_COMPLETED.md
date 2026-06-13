# Volunteer Management API — Product Requirements Document

## 1. Introduction

Community and nonprofit organizations live or die by the reliability of the volunteers who show up to staff their programs. This document specifies the Volunteer Management API, a backend service that coordinates the full arc of volunteer engagement — from publishing an opportunity and scheduling its shifts, through eligibility-gated signup, attendance, and hour logging, all the way to recognition milestones and reliability-driven suspensions.

The system is built around a finite-capacity model: each shift offers a fixed number of seats that volunteers reserve, commit to, and either honor or abandon. Layered on top of that allocation problem is a compliance regime — background-check tiers, signed liability waivers, completed safety training, and verified skills — that determines who is even permitted to occupy a seat. A parallel concern is corporate sponsorship, where a company can block-book a set of seats on a shift for a group event. Throughout, the platform must keep a careful ledger of who attended, how many hours they actually contributed, and how dependable each volunteer has proven to be over their lifetime, because those facts drive both automatic recognition and automatic suspension.

Because multiple coordinators and compliance staff act on the same shifts and volunteers concurrently, the API enforces optimistic concurrency at the two points where stale reads would corrupt finite resources: the seat count on a shift and the background-check tier on a volunteer. The remainder of this document defines the global contract that every endpoint obeys, the domain principles that cut across workflows, and the detailed business logic of each lifecycle.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting domain principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. A request that omits either header, or that carries a malformed or unrecognized value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Volunteer`, `ShiftCoordinator`, `ComplianceOfficer`, and `CorporateSponsor`.

A `Volunteer` is entity-backed. When `X-User-Role` is `Volunteer`, the `X-User-ID` value is the `id` of the acting `Volunteer` record; ownership checks on any resource that references a volunteer compare that resource's `volunteer_id` to `X-User-ID`. In particular, the actions a volunteer takes on a signup it owns — confirming, cancelling, and logging hours — require that the `volunteer_id` recorded on the target signup equal `X-User-ID`, and a mismatch is rejected with `ERR_NOT_SIGNUP_OWNER`.

The other three roles are operator identities rather than persisted entities. When `X-User-Role` is `ShiftCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ComplianceOfficer`: the identifier is opaque and is not matched against any entity. Likewise, when `X-User-Role` is `CorporateSponsor`, `X-User-ID` is an opaque operator identifier; the server treats it as a free-standing actor handle and does not bind it to a stored record. Broadly, a `ComplianceOfficer` owns background checks, the waiver and training catalogs, the volunteer lifecycle, and organization archival; a `ShiftCoordinator` owns opportunities, shifts, attendance, hour verification, and group allocation; a `CorporateSponsor` proposes and cancels corporate group blocks; and a `Volunteer` acts on their own profile, signups, waivers, and training. The precise authorization for each endpoint is given in the §4 table.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. The `id` is a unique, server-minted identifier formatted as a UUID, with no type prefix. The `created_at` field is an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, refreshed on any change to the resource. The `version` field is a system-managed integer that begins at 1 when the resource is created and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.6.

Three entities are deliberate exceptions: `VolunteerSkill`, `WaiverAcceptance`, and `TrainingCompletion` are append-only membership and signature records that are immutable after creation. Each of these carries only an `id` and a `created_at` — they have neither an `updated_at` nor a `version` field, and they are never mutated in place.

When a derived field on an entity is recomputed — for example a volunteer's reliability or a shift's seat count — that recomputation is itself a mutation of the owning entity: it refreshes the entity's `updated_at` and increments its `version`, exactly as a direct field edit would.

### 2.5. Cascading Consistency and Bubble-Up

The platform maintains immediate, atomic consistency across the entity hierarchy: every cascade triggered by a request completes inside that same request, never deferred. Three families of propagation recur throughout the workflows.

First, seat occupancy on a shift drives the shift's own state and bubbles up to its parent opportunity. A shift's `reserved_count` is the count of its signups that currently occupy a seat — those in `RESERVED`, `CONFIRMED`, `ATTENDED`, `HOURS_LOGGED`, or `HOURS_VERIFIED`. When that count reaches the shift's `capacity` the shift moves from `OPEN` to `FULL`; when a seat is released and the count falls below capacity the shift returns from `FULL` to `OPEN`. Every such oscillation re-evaluates the parent opportunity's `staffing_status`.

Second, cancellation cascades downward. Closing an opportunity cancels its open and full shifts, and cancelling a shift cancels the seat-holding signups beneath it and any allocated corporate group targeting it. These transitive chains are detailed in §3.

Third, a volunteer's computed standing bubbles up from the signup events beneath it. Verifying hours and recording a no-show both recompute the volunteer's aggregate figures — `total_verified_hours`, `reliability_score`, `milestone_tier`, and `lifetime_no_show_count` — and each such recompute bumps the volunteer's `version`. Whenever the server performs one of these automatic transitions because a derived criterion was satisfied or violated, it does so without requiring a separate client request against the affected resource.

### 2.6. Optimistic Concurrency Control

Two operations in the system read a parent resource, make a decision based on its current value, and then write — and at both of these points a stale client view could silently corrupt a finite or compliance-critical value. Each therefore requires the client to present the parent's last-observed `version` as a non-optional input, and rejects the write if that value no longer matches the parent's current `version`.

Signing a volunteer up for a shift is the first such point. The signup-create request must carry `expected_shift_version`, holding the `version` of the target shift that the client last read. If another writer has advanced the shift's `version` since then — for instance by occupying or releasing a seat — the create is rejected with `ERR_STALE_SHIFT_VERSION` at HTTP status 412. This serializes seat occupation so that the last seat can never be handed out beyond capacity on the strength of a stale `reserved_count`.

Deciding a background check is the second. The decide request must carry `expected_volunteer_version`, holding the `version` of the check's parent volunteer that the client last read. Because clearing a check recomputes the volunteer's `bg_check_tier`, applying the decision on top of a tier the client never observed would be unsafe; if the volunteer's `version` has advanced since the client read it, the decide is rejected with `ERR_STALE_VOLUNTEER_VERSION` at HTTP status 412.

Archiving an organization and withdrawing a volunteer are also version-guarded administrative actions. Archiving requires `expected_organization_version` matching the organization's current `version`, and a mismatch is rejected with `ERR_STALE_ORGANIZATION_VERSION` at HTTP status 412. Withdrawing a volunteer requires `expected_volunteer_version` matching the volunteer's current `version`, with a mismatch rejected as `ERR_STALE_VOLUNTEER_VERSION` at 412. Allocating a corporate group, which creates seat-occupying signups on the target shift, likewise requires `expected_shift_version` matching that shift's current `version`, with a mismatch rejected as `ERR_STALE_SHIFT_VERSION` at 412. Endpoints that do not appear in this section take no version field and perform no concurrency check.

### 2.7. Validation Ordering

Every request is validated through a fixed precedence so that the rejection a client sees reflects the first genuine obstacle, not an incidental later one. The ordering is: first, presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400); second, whether the acting role is permitted the operation at all (`ERR_UNAUTHORIZED`, 403); third, existence of every resource named by a path identifier, validated left to right (a `404` not-found specific to the missing resource); fourth, existence of every foreign key carried in the request body, resolved within the same organization (again a resource-specific `404`); fifth, that the governing organization is not archived for any create of a child resource (`ERR_ORGANIZATION_ARCHIVED`, 409); and sixth, that the target resource is in the correct state for the requested transition (a transition-specific `409`). Only after all of these pass does the system evaluate the operation-specific business rules described in §3, which themselves carry an internal ordering documented alongside the signup workflow.

Path identifiers are validated strictly left to right, and the first identifier in the path that does not resolve to an existing resource produces its own not-found error before any identifier further right is examined. Each not-found error is specific to the resource type that failed to resolve: a missing organization yields `ERR_ORGANIZATION_NOT_FOUND`, a missing volunteer `ERR_VOLUNTEER_NOT_FOUND`, a missing background check `ERR_BG_CHECK_NOT_FOUND`, a missing skill `ERR_SKILL_NOT_FOUND`, a missing waiver template `ERR_WAIVER_TEMPLATE_NOT_FOUND`, a missing training module `ERR_TRAINING_MODULE_NOT_FOUND`, a missing opportunity `ERR_OPPORTUNITY_NOT_FOUND`, a missing shift `ERR_SHIFT_NOT_FOUND`, a missing signup `ERR_SIGNUP_NOT_FOUND`, and a missing corporate group `ERR_GROUP_NOT_FOUND`. Foreign-key body fields — among them `organization_id`, `volunteer_id`, `skill_id`, `waiver_template_id`, `training_module_id`, `shift_id`, `target_shift_id`, `opportunity_id`, and the various `required_*` references on an opportunity — must each resolve to an existing entity, looked up globally by its `id` (the resolution is not additionally constrained to the acting organization); an unresolved reference yields the same resource-specific not-found error listed above. Separately, when a request omits a required input field or supplies one with the wrong type, it is rejected with `ERR_INVALID_REQUEST`; this request-shape validation runs ahead of the path-existence and foreign-key-existence checks above, so a malformed or incomplete body surfaces `ERR_INVALID_REQUEST` before any not-found error.

### 2.8. Time, Hours, and Numeric Precision

All timestamps exchanged with the API are ISO 8601 in UTC. Because much of the business logic is time-gated — a shift cannot be completed before it ends, a volunteer cannot be checked in before the shift starts, and background checks expire at a fixed instant — the server maintains a single logical "current clock." An administrative test-driving capability allows that clock to be set to a supplied `to_iso8601` instant so time-dependent transitions and lazy expiry can be exercised deterministically.

Hour quantities and the values derived from them are decimal numbers carried to two decimal places, rounded half up. Reliability is the one figure expressed as a whole number; it is computed, rounded half up to an integer, and then constrained to the range. The precise formulas, including the order in which rounding is applied, live in the workflow subsections of §3 where each figure is produced.

### 2.9. Organization Lifecycle and Reliability Policy

An `Organization` is the top of the hierarchy and the home of organization-wide policy. Beyond its `name`, an organization carries two governance thresholds set at creation: a `reliability_suspension_threshold` (defaulting to 40) that establishes the reliability floor below which a volunteer is suspended from new signups, and a `no_show_strike_limit` (defaulting to 3) that establishes the lifetime no-show count at which a volunteer is auto-suspended regardless of reliability. An organization's `status` begins at `ACTIVE` and may move to `ARCHIVED`; the two values are the only members of that enumeration. While an organization is `ARCHIVED`, every attempt to create a child resource beneath it is blocked with `ERR_ORGANIZATION_ARCHIVED`.

## 3. Business Logic & Workflows

### 3.1. Organizations, Volunteers, and the Catalog

The lifecycle begins with an `Organization`, created with a `name` and optionally with overrides for its `reliability_suspension_threshold` and `no_show_strike_limit`; absent overrides, those default to 40 and 3 respectively. A newly created organization has `status` `ACTIVE` and `version` 1. An organization may later be archived — a version-guarded action that moves its `status` to `ARCHIVED` and increments its `version` — after which no further children may be created under it.

Within an organization, a `ComplianceOfficer` or `ShiftCoordinator` registers a `Volunteer` by supplying the `organization_id`, the volunteer's `full_name`, and their `email`. The `email` must be unique within its `organization_id` across volunteers whose `status` is either `ACTIVE` or `SUSPENDED`; a withdrawn volunteer's address is freed for reuse. A collision against an `ACTIVE` or `SUSPENDED` volunteer's address is rejected with `ERR_INVALID_REQUEST`. A freshly registered volunteer starts with `status` `ACTIVE`, a `bg_check_tier` of `NONE`, a `reliability_score` of 100, a `milestone_tier` of `NONE`, a `lifetime_no_show_count` of 0, and `total_verified_hours` of 0. A volunteer's `status` enumeration is `ACTIVE`, `SUSPENDED`, or `WITHDRAWN`: a `SUSPENDED` volunteer is blocked from new signups but may be reinstated by the system, while `WITHDRAWN` is terminal. Withdrawal is a version-guarded administrative action that sets `status` to `WITHDRAWN` and increments the volunteer's `version`.

Several catalog resources hang off the organization. A `Skill` is created with its `organization_id`, a short `code` such as `FIRST_AID` that must be unique within that organization, and a human-readable `label`. A `WaiverTemplate` carries its `organization_id`, a `code` such as `LIABILITY_2026` unique within the organization, and a `revision` number that defaults to 1; an opportunity pins one exact revision and only acceptances of that precise revision count. A `TrainingModule` carries its `organization_id`, a `code` such as `SAFETY_101` unique within the organization, and a `valid_days` window that defaults to 730 — that is, two years — governing how long a completion of the module stays valid for prerequisite purposes. For each of these catalog resources, a `code` that collides with an existing code in the same organization is rejected with `ERR_INVALID_REQUEST`.

A volunteer's credentials are recorded through three append-only join records. Granting a skill creates a `VolunteerSkill` linking a `volunteer_id` to a `skill_id` with a `proficiency` that defaults to `VERIFIED` and may instead be `SELF_DECLARED`; only a `VERIFIED` grant satisfies an opportunity's skill requirement. Accepting a waiver creates a `WaiverAcceptance` linking a `volunteer_id` to a `waiver_template_id`, and the system snapshots the template's current `revision` into the record's `accepted_revision` at acceptance time. Recording training creates a `TrainingCompletion` linking a `volunteer_id` to a `training_module_id` with a `completed_at` timestamp supplied by the caller; the server derives the record's `expires_at` by adding the module's `valid_days` window (in days) to `completed_at`.

### 3.2. Background Checks and the Tier Ladder

A volunteer's eligibility for sensitive opportunities is governed by a background-check tier ladder, in which `NONE` is the lowest rung and the cleared tiers ascend as `BASIC`, then `STANDARD`, then `ENHANCED`. A `ComplianceOfficer` initiates a check by creating a `BackgroundCheck` with the `volunteer_id` it concerns, the `requested_tier` it will verify (one of `BASIC`, `STANDARD`, or `ENHANCED`), and optionally a `validity_days` window that defaults to 365 — one year — for how long the cleared result will remain valid. A new check has `status` `INITIATED`, with `cleared_at` and `valid_until` both null.

The check then advances through its own state machine, all transitions driven by the `ComplianceOfficer`. Starting a check moves it from `INITIATED` to `IN_PROGRESS`; if the check is not in `INITIATED` the start is rejected with `ERR_BG_CHECK_NOT_INITIATED`. Deciding a check carries a `decision` field that must be either `CLEARED` or `REJECTED`; any other value is rejected with `ERR_INVALID_BG_DECISION`, and a decide attempted on a check that is not `IN_PROGRESS` is rejected with `ERR_BG_CHECK_NOT_IN_PROGRESS`. The decide request also participates in optimistic concurrency: it must carry `expected_volunteer_version` matching the parent volunteer's current `version`, failing with `ERR_STALE_VOLUNTEER_VERSION` otherwise.

When a check is decided `CLEARED` (moving `IN_PROGRESS` to `CLEARED`), the server stamps `cleared_at` with the current clock and computes `valid_until` as `cleared_at` plus the validity window converted to seconds — that is, `validity_days` multiplied by 86,400 seconds per day, added to `cleared_at`, expressed in UTC to the millisecond. It then recomputes the parent volunteer's `bg_check_tier` and increments the volunteer's `version`. When a check is decided `REJECTED` (moving `IN_PROGRESS` to `REJECTED`, a terminal state), the server still recomputes the volunteer's `bg_check_tier` — which is unchanged unless that check had been the sole source of a tier — and increments the volunteer's `version`.

A volunteer's `bg_check_tier` is always the highest `requested_tier`, by rank, among that volunteer's background checks that are both `CLEARED` and not expired against the current clock; if no such check exists, the tier is `NONE`. Expiry is evaluated lazily: whenever a volunteer is read or their signup eligibility is being evaluated, any `CLEARED` check whose `valid_until` is now strictly before the current clock transitions from `CLEARED` to `EXPIRED`, after which the server recomputes the volunteer's `bg_check_tier` over the remaining cleared, non-expired checks — possibly lowering it — and increments the volunteer's `version`. An expired check is not dead: renewing it moves it from `EXPIRED` back to `INITIATED`, clearing both `cleared_at` and `valid_until` so the lifecycle can run again, and optionally accepting a fresh `validity_days`; renewing a check that is not `EXPIRED` is rejected with `ERR_BG_CHECK_NOT_EXPIRED`. An opportunity's tier requirement is met exactly when the rank of the volunteer's `bg_check_tier` is greater than or equal to the rank of the opportunity's required tier.

### 3.3. Opportunities and Shifts

A `ShiftCoordinator` creates an `Opportunity` under an organization by supplying the `organization_id` and a `title`, together with the optional eligibility gates that signups beneath it must satisfy: a `required_bg_tier` (defaulting to `NONE`), a list of `required_skill_ids` (defaulting to empty), a `required_waiver_template_id` (defaulting to null, meaning no waiver gate), a `required_training_module_id` (defaulting to null, meaning no training gate), and an `is_group_event` flag (defaulting to false) that marks whether the opportunity accepts corporate block registrations. An opportunity carries two independent state dimensions. Its `publication_status` — the lifecycle a coordinator drives — runs `DRAFT`, then `PUBLISHED`, then `CLOSED`. Its `staffing_status` is a computed dimension, either `UNDERSTAFFED` or `FULLY_STAFFED`, derived purely from the state of its child shifts.

A new opportunity is `DRAFT` with `staffing_status` `UNDERSTAFFED`. Publishing it advances `publication_status` from `DRAFT` to `PUBLISHED`; this requires the opportunity to currently be `DRAFT` (else `ERR_OPPORTUNITY_NOT_DRAFT`) and to have at least one child shift (else `ERR_OPPORTUNITY_HAS_NO_SHIFTS`), and as a side effect it recomputes the `staffing_status` from the child shifts. Closing it advances `publication_status` from `PUBLISHED` to `CLOSED`, the terminal publication state, requiring the opportunity to currently be `PUBLISHED` (else `ERR_OPPORTUNITY_NOT_PUBLISHED`). Closing cascades downward: every child shift currently in `OPEN` or `FULL` is moved to `CANCELLED`, and each such cancellation runs the full shift-cancel cascade described next, which in turn cancels the seat-holding signups beneath it.

The `staffing_status` is computed as follows. Consider only the opportunity's child shifts whose `status` is `OPEN`, `FULL`, or `COMPLETED`; cancelled shifts are excluded entirely. If that considered set is empty, the opportunity is `UNDERSTAFFED`. If every shift in the considered set is `FULL` or `COMPLETED`, the opportunity is `FULLY_STAFFED`. Otherwise it is `UNDERSTAFFED`. An opportunity with no non-cancelled shifts is therefore `UNDERSTAFFED`, never `FULLY_STAFFED`. A re-evaluation that leaves `staffing_status` unchanged is a no-op on the opportunity: its `updated_at` and `version` are bumped only when the computed `staffing_status` value actually differs from the stored one.

A `Shift` is created under an opportunity by a `ShiftCoordinator` with the `opportunity_id`, a `starts_at`, an `ends_at` that must be strictly after `starts_at` (else `ERR_INVALID_SHIFT_TIMES`), and a `capacity` that must be at least 1 (else `ERR_INVALID_CAPACITY`). A new shift is `OPEN` with `reserved_count` 0 and `group_reserved_seats` 0, and its creation re-evaluates the parent opportunity's `staffing_status`. The `group_reserved_seats` field tracks how many of the occupied seats are held by allocated corporate groups, counted within `reserved_count`. A shift's `status` enumeration is `OPEN`, `FULL`, `CANCELLED`, or `COMPLETED`, where `FULL` is the compound state entered exactly when `reserved_count` equals `capacity` and exited back to `OPEN` when a release drops the count below capacity.

Cancelling a shift is permitted only while it is `OPEN` or `FULL` (else `ERR_SHIFT_NOT_CANCELLABLE`); it may be triggered directly by a coordinator or as a cascade from closing the opportunity. Cancellation moves the shift to `CANCELLED` and runs three effects: every seat-holding signup in `RESERVED` or `CONFIRMED` is moved to `CANCELLED` and its seat released, with no reliability penalty applied to the volunteer; any `ALLOCATED` corporate group whose `target_shift_id` is this shift is itself moved to `CANCELLED` (its group-placeholder signups having already been cancelled by the seat cascade); and the parent opportunity's `staffing_status` is re-evaluated.

Completing a shift is permitted only while it is `OPEN` or `FULL` (else `ERR_SHIFT_NOT_COMPLETABLE`) and only once the current clock has reached or passed the shift's `ends_at` (else `ERR_SHIFT_NOT_ENDED`). Completion moves the shift to `COMPLETED` and increments the shift's `version`. As its central side effect, every signup still in `CONFIRMED` with no attendance decision is moved to `NO_SHOW`, and each such transition runs the per-signup no-show reliability cascade described in §3.5.

### 3.4. Shift Signup and the Eligibility Chain

The heart of the platform is a volunteer claiming a seat on a shift. A `Volunteer` signs up against a specific shift by supplying their `volunteer_id` (which must equal `X-User-ID`) and `expected_shift_version`. A successful signup creates a `Signup` in `RESERVED` status, increments the shift's `reserved_count` by one, and increments the shift's `version`; if that occupancy brings `reserved_count` to `capacity`, the shift moves from `OPEN` to `FULL` and the parent opportunity's `staffing_status` is re-evaluated. A signup's `status` enumeration is `RESERVED`, `CONFIRMED`, `ATTENDED`, `HOURS_LOGGED`, `HOURS_VERIFIED`, `CANCELLED`, or `NO_SHOW`. A signup also carries a `shift_id`, a `corporate_group_id` (null for an individual signup, set when the signup was created from a group block), a `logged_hours` field (null until the volunteer reports hours), a `verified_hours` field (null until verification), and a `provisional_hours` field (defaulting to 0).

Before a seat is granted, the request runs an ordered eligibility chain whose checks are evaluated in a fixed sequence, so that an earlier obstacle masks a later one. After the universal header, authorization, path-existence, body-foreign-key, and organization-not-archived gates of §2.7 have passed, the `expected_shift_version` optimistic-concurrency check of §2.6 is evaluated next — a mismatch rejects with `ERR_STALE_SHIFT_VERSION` (412) before any of the signup-specific rules below run — and then those rules apply strictly in the following order:

1. **State of the target.** The shift must be in a state that can accept a signup; a signup against a non-open shift surfaces through the capacity rule below rather than a separate state code, but the target must resolve as a real shift.
2. **Volunteer eligibility.** The acting volunteer's `status` must be `ACTIVE`. A `SUSPENDED` or `WITHDRAWN` volunteer is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE`.
3. **Time conflict.** The volunteer may not already hold a seat-occupying signup on another shift whose scheduled interval overlaps this one. Intervals are half-open over `[starts_at, ends_at)`: two shifts conflict when their intervals overlap, but shifts that merely touch at an endpoint — one ending exactly when the other begins — do not conflict. A genuine overlap is rejected with `ERR_SHIFT_TIME_CONFLICT`.
4. **Background-check tier.** The rank of the volunteer's `bg_check_tier` must be greater than or equal to the rank of the opportunity's `required_bg_tier`, with lazy expiry applied against the current clock before the comparison. A shortfall is rejected with `ERR_BG_TIER_INSUFFICIENT`.
5. **Skill gate.** For every `Skill.id` listed in the opportunity's `required_skill_ids`, the volunteer must hold a `VolunteerSkill` for that skill with `proficiency` equal to `VERIFIED`. Any missing verified skill is rejected with `ERR_SKILL_REQUIREMENT_NOT_MET`.
6. **Waiver prerequisite.** If the opportunity sets a `required_waiver_template_id`, the volunteer must have a `WaiverAcceptance` for that template whose `accepted_revision` equals the template's current `revision`. Otherwise the signup is rejected with `ERR_WAIVER_NOT_ACCEPTED`.
7. **Training prerequisite.** If the opportunity sets a `required_training_module_id`, the volunteer must have a `TrainingCompletion` for that module that has not lapsed — that is, whose `expires_at` is at or after the current clock. Otherwise the signup is rejected with `ERR_TRAINING_NOT_COMPLETED`.
8. **Duplicate signup.** The volunteer must not already hold a seat-occupying signup — one in `RESERVED`, `CONFIRMED`, `ATTENDED`, `HOURS_LOGGED`, or `HOURS_VERIFIED` — on this same shift. A duplicate is rejected with `ERR_DUPLICATE_SIGNUP`.
9. **Capacity.** A seat must be available: the shift's `reserved_count` must be strictly less than its `capacity`. A full shift is rejected with `ERR_SHIFT_FULL`.

Once reserved, the volunteer confirms their intent, moving the signup from `RESERVED` to `CONFIRMED`; confirmation requires the signup to currently be `RESERVED` (else `ERR_SIGNUP_NOT_RESERVED`) and the acting volunteer to own it (else `ERR_NOT_SIGNUP_OWNER`). A volunteer may cancel a signup while it is `RESERVED` or `CONFIRMED` (else `ERR_SIGNUP_NOT_CANCELLABLE`), again only on a signup they own. Cancellation moves the signup to `CANCELLED`, releases the seat by decrementing the parent shift's `reserved_count` by one, increments the shift's `version`, and — if the shift had been `FULL` and is now below capacity — returns it to `OPEN` and re-evaluates the parent opportunity's `staffing_status`. A volunteer cancellation carries no reliability penalty.

### 3.5. Attendance, No-Shows, and Reliability

On the day of the shift, a `ShiftCoordinator` checks a confirmed volunteer in, moving the signup from `CONFIRMED` to `ATTENDED`. Check-in requires the signup to currently be `CONFIRMED` (else `ERR_SIGNUP_NOT_CONFIRMED`) and the current clock to have reached or passed the parent shift's `starts_at` (else `ERR_SHIFT_NOT_STARTED`). At check-in the server sets the signup's `provisional_hours` from the shift's scheduled duration: it takes the difference between the shift's `ends_at` and `starts_at` in seconds, divides by 3,600 to obtain hours, and rounds that half up to two decimal places. This provisional figure is an upper-bound estimate of the volunteer's contribution, standing in until actual hours are verified.

Alternatively, a coordinator may mark a confirmed volunteer as a no-show, moving the signup from `CONFIRMED` to `NO_SHOW`; this is also the automatic outcome for any still-confirmed signup when its shift is completed. Marking no-show requires the signup to currently be `CONFIRMED` (else `ERR_SIGNUP_NOT_CONFIRMED`). The no-show cascade is the system's reliability serialization point and runs several effects in turn: the seat is released, decrementing the parent shift's `reserved_count` by one and returning the shift from `FULL` to `OPEN` (with the staffing bubble-up) if it now sits below capacity; the volunteer's `lifetime_no_show_count` is recomputed as the count of that volunteer's signups currently in `NO_SHOW`; the volunteer's `reliability_score` is recomputed; and the shift's `version` and the volunteer's `version` are each incremented. If, after the recompute, the volunteer's `reliability_score` is strictly below the organization's `reliability_suspension_threshold`, or the volunteer's `lifetime_no_show_count` is greater than or equal to the organization's `no_show_strike_limit`, the volunteer's `status` is transitioned to `SUSPENDED`. This auto-suspension only fires on a volunteer whose `status` is currently `ACTIVE`; a volunteer already `SUSPENDED` or `WITHDRAWN` is left in place.

The `reliability_score` is a whole number derived from the volunteer's own history. Let the kept count be the number of that volunteer's signups in `HOURS_VERIFIED`, and let the broken count be the volunteer's `lifetime_no_show_count` — their signups currently in `NO_SHOW`. Signups in any other status contribute to neither count. If the sum of kept and broken is zero, the `reliability_score` is exactly 100. Otherwise, take the attendance ratio as kept divided by the sum of kept and broken, compute a raw value of 100 multiplied by that ratio minus a penalty of 8 points for each no-show in the broken count, round that raw value half up to a whole number, and then clamp the result to lie between 0 and 100 inclusive. A volunteer therefore loses ground both proportionally, as no-shows dilute their attendance ratio, and additively, through the fixed 8-point charge per no-show.

### 3.6. Hour Logging, Verification, and Recognition Milestones

After attending, a volunteer logs the hours they actually contributed, moving the signup from `ATTENDED` to `HOURS_LOGGED`. The log-hours request carries a `logged_hours` value and requires the signup to currently be `ATTENDED` (else `ERR_SIGNUP_NOT_ATTENDED`) and the acting volunteer to own it (else `ERR_NOT_SIGNUP_OWNER`). The reported hours must be greater than zero (else `ERR_INVALID_HOURS`) and must not exceed the shift's scheduled duration in hours (else `ERR_HOURS_EXCEED_SHIFT`, returned at HTTP 422). A successful log stores the value in `logged_hours`.

A `ShiftCoordinator` then verifies the logged hours, moving the signup from `HOURS_LOGGED` to `HOURS_VERIFIED`, the terminal success state; verification requires the signup to currently be `HOURS_LOGGED` (else `ERR_SIGNUP_NOT_LOGGED`). Verification sets the signup's `verified_hours` to the smaller of the volunteer's `logged_hours` and the signup's `provisional_hours` — that is, the logged figure capped at the scheduled duration — rounded half up to two decimal places. Because the cap can bind, `verified_hours` may be strictly less than `provisional_hours`, and only `verified_hours` ever feeds the volunteer's lifetime total. Should the coordinator instead reject the logged hours, the signup moves from `HOURS_LOGGED` back to `ATTENDED`, clearing `logged_hours` back to null so the volunteer can re-log; rejection likewise requires the signup to currently be `HOURS_LOGGED` (else `ERR_SIGNUP_NOT_LOGGED`).

Verification triggers the recognition chain on the volunteer. First, the volunteer's `total_verified_hours` is recomputed from every signup of theirs in `HOURS_VERIFIED`, taken in order of the signup's creation timestamp. The rounding order is mandatory and runs round-per-line-item then sum: each contributing signup's `verified_hours` is rounded half up to two decimal places, those per-line values are summed, and the sum is itself rounded half up to two decimal places. Summing first and rounding once would diverge in the cents and is not permitted. Then the volunteer's `reliability_score` is recomputed exactly as in §3.5, since verifying hours adds to the kept count. Finally the volunteer's `milestone_tier` is recomputed, and the volunteer's `version` is incremented.

The `milestone_tier` ladder rises `NONE`, `BRONZE`, `SILVER`, `GOLD`, `PLATINUM`. From the volunteer's `total_verified_hours`, a candidate tier is chosen against inclusive lower bounds: `PLATINUM` once the total reaches at least 500 hours, otherwise `GOLD` at no fewer than 200 hours, otherwise `SILVER` at no fewer than 100 hours, otherwise `BRONZE` at no fewer than 25 hours, otherwise `NONE`. Because the bounds are inclusive, a total of exactly 25.00 hours earns `BRONZE` while 24.99 remains `NONE`. The stored `milestone_tier` is the higher, by rank, of the volunteer's current tier and this candidate: the tier is monotonic and non-decreasing, so it never drops even if a volunteer's verified total later falls. Each genuine increase in the stored tier is a recognition milestone.

### 3.7. Corporate Group Blocks

Corporate sponsorship lets a company reserve a block of seats on a single shift. A `CorporateSponsor` — or a `ShiftCoordinator` acting on their behalf — proposes a `CorporateGroup` by supplying the `opportunity_id`, a `sponsor_name`, the number of `requested_seats` (which must be at least 1, else `ERR_INVALID_SEATS`), and the `target_shift_id` the block applies to. A new group is `PROPOSED`, with `allocated_seat_count` 0. The group's `status` enumeration is `PROPOSED`, `APPROVED`, `ALLOCATED`, `REJECTED`, or `CANCELLED`.

A `ShiftCoordinator` triages a proposed group. Approval moves it from `PROPOSED` to `APPROVED` and requires three things: the group must currently be `PROPOSED` (else `ERR_GROUP_NOT_PROPOSED`), the parent opportunity must have `is_group_event` set to true (else `ERR_OPPORTUNITY_NOT_GROUP_EVENT`), and the parent opportunity's `publication_status` must be `PUBLISHED` (else `ERR_OPPORTUNITY_NOT_PUBLISHED`). Rejection moves a still-`PROPOSED` group to `REJECTED`, a terminal state, again requiring it to be `PROPOSED` (else `ERR_GROUP_NOT_PROPOSED`).

Allocation is where a block becomes concrete seats. Allocating an approved group moves it from `APPROVED` to `ALLOCATED` and is version-guarded on the target shift: the request carries `expected_shift_version` matching the shift's current `version` (else `ERR_STALE_SHIFT_VERSION`). The group must currently be `APPROVED` (else `ERR_GROUP_NOT_APPROVED`), the target shift must be `OPEN` (else `ERR_SHIFT_NOT_OPEN`), and the shift's remaining capacity — its `capacity` minus its `reserved_count` — must be at least the `requested_seats` (else `ERR_INSUFFICIENT_SHIFT_CAPACITY`). On success the server creates `requested_seats` group-placeholder signups on the target shift, each in `RESERVED` with `corporate_group_id` set to this group and `volunteer_id` left null, each occupying a seat; it raises the shift's `reserved_count` and its `group_reserved_seats` by `requested_seats`; it sets the group's `allocated_seat_count` to `requested_seats`; and it increments the shift's `version` by one per created signup. If the added seats bring `reserved_count` to `capacity`, the shift moves to `FULL` and the parent opportunity's `staffing_status` is re-evaluated.

A sponsor may cancel a group while it is `PROPOSED` or `APPROVED` (else `ERR_GROUP_NOT_CANCELLABLE`), moving it to `CANCELLED`. An already-`ALLOCATED` group is not cancelled directly by the sponsor; instead it moves to `CANCELLED` only as a cascade when its target shift is cancelled, at which point the group's placeholder signups have already been cancelled by the shift-cancel seat cascade.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify, transition, or read an existing resource return a `200 OK` status code. The clock-control endpoint, used only for deterministic testing of time-gated behavior, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vm/organizations` | Create an organization | ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/organizations` | List organizations | Volunteer, ComplianceOfficer, ShiftCoordinator, CorporateSponsor |
| GET | `/vm/organizations/{orgId}` | Get an organization | Volunteer, ComplianceOfficer, ShiftCoordinator, CorporateSponsor |
| POST | `/vm/organizations/{orgId}/archive` | Archive an organization | ComplianceOfficer |
| POST | `/vm/volunteers` | Register a volunteer | ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/volunteers` | List volunteers | ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/volunteers/{volunteerId}` | Get a volunteer | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/volunteers/{volunteerId}/withdraw` | Withdraw a volunteer | ComplianceOfficer |
| POST | `/vm/background-checks` | Initiate a background check | ComplianceOfficer |
| GET | `/vm/background-checks` | List background checks | ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/background-checks/{checkId}` | Get a background check | ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/background-checks/{checkId}/start` | Start a check (INITIATED → IN_PROGRESS) | ComplianceOfficer |
| POST | `/vm/background-checks/{checkId}/decide` | Decide a check CLEARED/REJECTED | ComplianceOfficer |
| POST | `/vm/background-checks/{checkId}/renew` | Renew an EXPIRED check | ComplianceOfficer |
| POST | `/vm/skills` | Create a skill | ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/skills` | List skills | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/skills/{skillId}` | Get a skill | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/volunteer-skills` | Grant a skill to a volunteer | ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/volunteer-skills` | List volunteer-skill grants | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/volunteer-skills/{volunteerSkillId}` | Get a volunteer-skill grant | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/waiver-templates` | Create a waiver template | ComplianceOfficer |
| GET | `/vm/waiver-templates` | List waiver templates | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/waiver-templates/{waiverTemplateId}` | Get a waiver template | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/waiver-acceptances` | Accept a waiver template | Volunteer, ComplianceOfficer |
| GET | `/vm/waiver-acceptances` | List waiver acceptances | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/waiver-acceptances/{waiverAcceptanceId}` | Get a waiver acceptance | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/training-modules` | Create a training module | ComplianceOfficer |
| GET | `/vm/training-modules` | List training modules | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/training-modules/{trainingModuleId}` | Get a training module | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/training-completions` | Record a training completion | Volunteer, ComplianceOfficer |
| GET | `/vm/training-completions` | List training completions | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/training-completions/{trainingCompletionId}` | Get a training completion | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/opportunities` | Create an opportunity (DRAFT) | ShiftCoordinator |
| GET | `/vm/opportunities` | List opportunities | Volunteer, ComplianceOfficer, ShiftCoordinator, CorporateSponsor |
| GET | `/vm/opportunities/{opportunityId}` | Get an opportunity | Volunteer, ComplianceOfficer, ShiftCoordinator, CorporateSponsor |
| POST | `/vm/opportunities/{opportunityId}/publish` | Publish an opportunity | ShiftCoordinator |
| POST | `/vm/opportunities/{opportunityId}/close` | Close an opportunity (cascade-cancel shifts) | ShiftCoordinator |
| POST | `/vm/shifts` | Create a shift | ShiftCoordinator |
| GET | `/vm/shifts` | List shifts | Volunteer, ComplianceOfficer, ShiftCoordinator, CorporateSponsor |
| GET | `/vm/shifts/{shiftId}` | Get a shift | Volunteer, ComplianceOfficer, ShiftCoordinator, CorporateSponsor |
| POST | `/vm/shifts/{shiftId}/cancel` | Cancel a shift (cascade-cancel signups) | ShiftCoordinator |
| POST | `/vm/shifts/{shiftId}/complete` | Complete a shift (after end) | ShiftCoordinator |
| POST | `/vm/shifts/{shiftId}/signups` | Sign up for a shift | Volunteer |
| GET | `/vm/signups` | List signups | Volunteer, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/signups/{signupId}` | Get a signup | Volunteer, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/signups/{signupId}/confirm` | Confirm a reserved signup | Volunteer |
| POST | `/vm/signups/{signupId}/cancel` | Cancel a signup (release seat) | Volunteer |
| POST | `/vm/signups/{signupId}/check-in` | Check a confirmed volunteer in | ShiftCoordinator |
| POST | `/vm/signups/{signupId}/mark-no-show` | Mark a confirmed volunteer as no-show | ShiftCoordinator |
| POST | `/vm/signups/{signupId}/log-hours` | Log hours after attending | Volunteer |
| POST | `/vm/signups/{signupId}/verify-hours` | Verify logged hours | ShiftCoordinator |
| POST | `/vm/signups/{signupId}/reject-hours` | Reject logged hours (back to ATTENDED) | ShiftCoordinator |
| POST | `/vm/corporate-groups` | Propose a corporate group block | CorporateSponsor, ShiftCoordinator |
| GET | `/vm/corporate-groups` | List corporate groups | CorporateSponsor, ComplianceOfficer, ShiftCoordinator |
| GET | `/vm/corporate-groups/{groupId}` | Get a corporate group | CorporateSponsor, ComplianceOfficer, ShiftCoordinator |
| POST | `/vm/corporate-groups/{groupId}/approve` | Approve a proposed group | ShiftCoordinator |
| POST | `/vm/corporate-groups/{groupId}/reject` | Reject a proposed group | ShiftCoordinator |
| POST | `/vm/corporate-groups/{groupId}/allocate` | Allocate an approved group into signups | ShiftCoordinator |
| POST | `/vm/corporate-groups/{groupId}/cancel` | Cancel a proposed/approved group | CorporateSponsor |
| POST | `/_clock/set_current_utc` | Test-only: set the server's current UTC clock | ComplianceOfficer, ShiftCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_SIGNUP_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ORGANIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_VOLUNTEER_NOT_FOUND` | 404 Not Found |
| `ERR_BG_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_SKILL_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_MODULE_NOT_FOUND` | 404 Not Found |
| `ERR_OPPORTUNITY_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNUP_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_ORGANIZATION_ARCHIVED` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_ELIGIBLE` | 403 Forbidden |
| `ERR_BG_CHECK_NOT_INITIATED` | 409 Conflict |
| `ERR_BG_CHECK_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_BG_CHECK_NOT_EXPIRED` | 409 Conflict |
| `ERR_INVALID_BG_DECISION` | 400 Bad Request |
| `ERR_OPPORTUNITY_NOT_DRAFT` | 409 Conflict |
| `ERR_OPPORTUNITY_NOT_PUBLISHED` | 409 Conflict |
| `ERR_OPPORTUNITY_HAS_NO_SHIFTS` | 409 Conflict |
| `ERR_OPPORTUNITY_NOT_GROUP_EVENT` | 409 Conflict |
| `ERR_SHIFT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIFT_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_SHIFT_NOT_ENDED` | 409 Conflict |
| `ERR_SHIFT_NOT_STARTED` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_SHIFT_TIMES` | 400 Bad Request |
| `ERR_INVALID_CAPACITY` | 400 Bad Request |
| `ERR_SIGNUP_NOT_RESERVED` | 409 Conflict |
| `ERR_SIGNUP_NOT_CONFIRMED` | 409 Conflict |
| `ERR_SIGNUP_NOT_ATTENDED` | 409 Conflict |
| `ERR_SIGNUP_NOT_LOGGED` | 409 Conflict |
| `ERR_SIGNUP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DUPLICATE_SIGNUP` | 409 Conflict |
| `ERR_SHIFT_FULL` | 409 Conflict |
| `ERR_SHIFT_TIME_CONFLICT` | 409 Conflict |
| `ERR_INVALID_HOURS` | 400 Bad Request |
| `ERR_HOURS_EXCEED_SHIFT` | 422 Unprocessable Entity |
| `ERR_BG_TIER_INSUFFICIENT` | 403 Forbidden |
| `ERR_SKILL_REQUIREMENT_NOT_MET` | 403 Forbidden |
| `ERR_WAIVER_NOT_ACCEPTED` | 403 Forbidden |
| `ERR_TRAINING_NOT_COMPLETED` | 403 Forbidden |
| `ERR_GROUP_NOT_PROPOSED` | 409 Conflict |
| `ERR_GROUP_NOT_APPROVED` | 409 Conflict |
| `ERR_GROUP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_SHIFT_CAPACITY` | 409 Conflict |
| `ERR_INVALID_SEATS` | 400 Bad Request |
| `ERR_STALE_SHIFT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_VOLUNTEER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORGANIZATION_VERSION` | 412 Precondition Failed |
