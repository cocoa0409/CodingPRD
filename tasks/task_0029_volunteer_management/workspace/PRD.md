# Volunteer Management API — Product Requirements Document

## 1. Introduction

Community-service organizations need a single platform that can take a stranger off the street, verify their identity, capture and review the skills they claim, surface the activities for which they actually qualify, run the on-the-day operational mechanics of check-in and check-out, and turn the resulting service hours into points and certificates that volunteers can use, share, and redeem. The Volunteer Management API is the back-office service that supports that end-to-end journey. It coordinates identity verification with an external identity provider, gates sensitive work behind background checks, lets organizers publish activities through a controlled review process, matches volunteers to those activities by skill and geography, manages the live attendance loop, computes credited hours under three configurable rules, awards and expires points on a long horizon, issues and verifies certificates, and emits synchronization events to instant-messaging, identity-provider, and partner-organization channels along the way.

The system is intended for three distinct kinds of operator: rank-and-file volunteers acting on their own records and applications; organizers, who are themselves verified volunteers but additionally host and run activities; and platform administrators, who govern the catalog, decide reviews, clear background checks, run the point mall, and issue certificates. Every operation is auditable, every numeric calculation is reproducible, and every concurrent contention point has a defined winner and a named loser error. The contract below specifies the structural envelope, the cross-cutting rules that apply to every workflow, the per-workflow business logic that an implementer must reconstruct from prose, and the catalog of endpoints and error codes that the test harness will exercise.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must include two headers that together identify the caller and authorize the action: `X-User-ID` carries the caller's identifier and `X-User-Role` carries the caller's declared role. A request that is missing either header, or whose `X-User-Role` value is not one of the three valid role names, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not in the endpoint's authorized list is rejected with `ERR_FORBIDDEN`.

The platform recognizes exactly three role names, spelled exactly as follows: `Volunteer`, `Organizer`, and `SkillAdmin`.

When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks on any resource that references a `Volunteer` (for example `Application.volunteer_id`, `RedemptionOrder.volunteer_id`, or `VolunteerSkill.volunteer_id`) compare the resource's foreign-key field to `X-User-ID` and reject mismatches with `ERR_FORBIDDEN`. When `X-User-Role` is `Organizer`, `X-User-ID` is likewise the `id` of an acting `Volunteer` row (an organizer is itself a verified volunteer); ownership checks on activities compare `Activity.organizer_id` to `X-User-ID`. The same persisted `id` may legitimately act as `Volunteer` on activities they did not create and as `Organizer` on activities where `Activity.organizer_id` equals their `id` — there is one row, two role hats, and authorization keys off `Activity.organizer_id` rather than off any separate user table. When `X-User-Role` is `SkillAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reviewer_id` on `VolunteerSkill` or as `approver_id` on `HourAdjustment` where a scaffold transition writes it) but does not compare it to any entity's `id` for ownership purposes.

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

List endpoints accept two query-string parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when the caller omits it, has a minimum of 1, and a maximum of 100; values outside that closed range are rejected with `ERR_INVALID_INPUT`. The `offset` parameter defaults to 0 and may be any non-negative integer. Results are sorted by `created_at` ascending unless an endpoint's narrative says otherwise. The `meta` object on a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true when `offset + limit < total_count`.

### 2.4. Common Resource Properties and Versioning

Every resource minted by the server carries an `id` field that is a server-minted UUID with no type prefix, and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits. Resources that participate in the optimistic-concurrency contract additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version` field that starts at 1 on creation and increments by exactly 1 on every successful mutation. The two link entities `VolunteerSkill` and `ActivityRole`, the append-only `AuditLog`, and the append-only `PartnerSyncEvent` are exceptions: they carry only `id` and `created_at`, and have neither `updated_at` nor `version`.

Optimistic concurrency control is offered on mutating endpoints that accept a request body. When a caller includes a `version` field in the request body, the server compares the supplied value against the current row's `version` and rejects a mismatch with `ERR_VERSION_CONFLICT`. When the caller omits the `version` field entirely, the OCC check is skipped and the mutation proceeds (still subject to every other validation). On every successful mutation, the server bumps the row's `version` by one and refreshes `updated_at` to the new server time. Cascaded mutations to a parent or sibling row (for example, when a check-out completes an `Application` and increases `Volunteer.total_service_hours` in the same operation) bump the cascaded entity's `version` and refresh its `updated_at` too.

### 2.5. Numeric Precision and Rounding

All distance values in kilometres, all hour values, and the `coefficient` on `ActivityRole` are stored and returned with exactly two decimal places. Arithmetic that produces a fraction beyond two decimals is rounded half up (a value of 0.125 rounds to 0.13). Point quantities — `points_balance`, `points_awarded`, `total_points`, `point_cost`, and the `quantity` field on `RedemptionOrder` — are integers; any computation that yields a non-integer point total is floored to an integer rather than rounded. Geographic latitude (`home_lat`, `location_lat`, `check_in_lat`) is constrained to the closed range from -90 to 90, and longitude (`home_lng`, `location_lng`, `check_in_lng`) to the closed range from -180 to 180; values outside those ranges are rejected with `ERR_INVALID_INPUT`.

### 2.6. Nested-Path Validation Order

When a URL contains multiple resource-id segments, each segment is validated left to right against the underlying row's existence; the first segment that does not resolve causes the request to be rejected with `ERR_NOT_FOUND` and no later segment is consulted. The same `ERR_NOT_FOUND` is returned when a request body references a foreign key — a `Skill.id`, an `Activity.id`, an `ActivityRole.id`, a `PointMallItem.id`, a `CertificateTemplate.id`, or a `Volunteer.id` — that does not resolve to a stored row. A foreign key that resolves to a real row but does not belong to the surrounding parent (the most common case is an `ActivityRole` whose `activity_id` does not match the surrounding `Activity.id` on apply or on role definition) is a different failure: it is rejected with `ERR_INVALID_REFERENCE`.

### 2.7. Validation Priority

When multiple validations would fire on the same request, the system evaluates them in a fixed priority order so that the most fundamental failure surfaces first. The order is: authentication header presence first; then role authorization for the endpoint; then path-segment existence (left to right); then request-body foreign-key existence; then cross-aggregate ownership (the `Volunteer` or `Organizer` actually owns the resource being acted on); then nested-reference well-formedness (the `ActivityRole` belongs to the surrounding `Activity`); then state-machine permissibility for the requested transition; then identity-verification for any volunteer-initiated activity action; then the background-check requirement when the target activity needs sensitive clearance; then the skill-tag match against `Activity.required_skill_codes`; then recruitment-window and time-conflict checks; then geographic-distance, uniqueness, and quota-related checks; then field-level format validation; and last, optimistic-concurrency version comparison. The practical consequence is, for instance, that an unauthenticated caller who is also targeting a non-existent activity always receives `ERR_UNAUTHENTICATED`, never `ERR_NOT_FOUND`; that a caller whose identity is unverified and who would also fail a skill-match check always receives `ERR_IDENTITY_NOT_VERIFIED` first; and that a stale `version` on a request that would also have failed a quota check surfaces the quota error first, with `ERR_VERSION_CONFLICT` reserved for the case where every other check passed.

### 2.8. Hierarchical Consistency and Cascades

Mutations that update a parent entity propagate to whichever child or related entity their business semantics demand, and every cascaded write bumps the touched row's `version` and refreshes its `updated_at`. The most consequential cascades to be aware of are: an `Activity` automatically transitioning to `COMPLETED` simultaneously stamps `check_out_at = Activity.end_at` on every `Application` still in `CHECKED_IN`, transitions those applications to `COMPLETED`, runs the service-hour and point-earning calculations against each, increments `Volunteer.total_completed_activities` and `Volunteer.total_service_hours` and `Volunteer.points_balance` accordingly, and at the same time transitions every `Application` still in `APPROVED` (with no `check_in_at`) to `NO_SHOW`. A `RedemptionOrder` fulfillment decrements `PointMallItem.stock` and `Volunteer.points_balance`, and if `PointMallItem.stock` reaches zero the parent item cascades from `ACTIVE` to `OUT_OF_STOCK`. Approving a `HourAdjustment` mutates the linked `Application.adjusted_hours`, recomputes `Application.points_awarded`, and propagates the deltas to `Volunteer.total_service_hours` and `Volunteer.points_balance`. Each of these cascades is a single logical transaction: either every touched row's `version` and `updated_at` advance together, or none of them advance.

### 2.9. Concurrency Guarantees

Every operation that races for a finite resource is serialized at commit time with a defined winner and a defined loser error.

When two organizers simultaneously try to approve the last available position on the same activity, an atomic compare-and-increment on `Activity.filled_positions` admits at most `Activity.position_quota` approvals; the loser receives `ERR_QUOTA_EXCEEDED`. When an organizer's approve and a volunteer's withdraw arrive at the same `Application` simultaneously while it is still `APPLIED`, first-writer-wins on `Application.status` admits exactly one transition; the loser receives `ERR_INVALID_STATE`. When two `SkillAdmin` operators simultaneously fulfill two `RedemptionOrder` rows for the same `PointMallItem` and the combined quantity exceeds available `PointMallItem.stock`, the atomic compare-and-decrement on `PointMallItem.stock` allows the first to commit and the second's stock check fails with `ERR_INSUFFICIENT_STOCK`. When two `RedemptionOrder` fulfillments for the same volunteer race and the combined `total_points` would drive `Volunteer.points_balance` below zero, the atomic compare-and-decrement on `Volunteer.points_balance` admits one and the loser receives `ERR_INSUFFICIENT_POINTS`. When two `SkillAdmin` operators simultaneously approve and reject the same `HourAdjustment`, first-writer-wins on `HourAdjustment.status` admits one transition and the loser receives `ERR_INVALID_STATE`. When a single volunteer fires two simultaneous applications to two activities whose time windows overlap, the conflict check is evaluated at commit; at most one application becomes `APPROVED` per overlapping window, and the loser (resolved by ascending `Application.id`) receives `ERR_TIME_CONFLICT`.

### 2.10. Audit and Synchronization

The platform maintains an append-only `AuditLog` for every hour-adjustment and every certificate event, capturing `actor_role`, `actor_id`, `action_type`, `target_entity`, `target_id`, and a `payload` JSON snapshot of the action. The recognized `action_type` values are exactly `HOUR_ADJUST_REQUEST`, `HOUR_ADJUST_APPROVE`, `HOUR_ADJUST_REJECT`, `CERTIFICATE_ISSUE`, `CERTIFICATE_REISSUE`, and `CERTIFICATE_REVOKE`; no other action types are written. Separately, the platform maintains an append-only `PartnerSyncEvent` ledger of outbound notifications to downstream systems, each carrying a `channel` of `IM`, `IDENTITY_PROVIDER`, or `PARTNER_ORG`, plus an `event_type` string and a `payload`. Both ledgers are exposed as list endpoints to `SkillAdmin` only, and both are read-only — the system writes to them as a side effect of business transitions, never via direct mutation.

### 2.11. Server Clock and Test-Driven Time

All time-gated transitions on `Activity` (publish-to-recruiting, recruiting-to-running, running-to-completed), the hours-archival sweep, and the points-expiration sweep are driven by the server's logical clock. A `SkillAdmin`-only test-driving capability advances that logical clock to a supplied `target_time` ISO 8601 UTC instant; advancing the clock executes every transition that has now become due and runs both sweeps. The current clock value can be read by any role.

## 3. Business Logic & Workflows

### 3.1. Volunteer Onboarding, Identity, and Background Check

A new `Volunteer` record is registered into the system by a `SkillAdmin` operator who supplies the volunteer's `full_name` (1 to 100 characters), an `id_number_hash` (a hash of the national identifier, unique across the platform — duplicates are rejected with `ERR_INVALID_INPUT`), and the volunteer's home coordinates as `home_lat` and `home_lng`. The newly created record carries `identity_verification_status` of `PENDING`, `background_check_status` of `NONE`, a `total_service_hours` of 0, a `total_completed_activities` of 0, a `points_balance` of 0, and an `archived_hours` of 0. All five computed values may only be advanced by the side effects defined elsewhere in this document, never written directly via the registration call.

After registration, identity verification proceeds along a two-state path: a `SkillAdmin` either confirms the volunteer's identity (advancing `identity_verification_status` from `PENDING` to `VERIFIED`) or rejects it (advancing `identity_verification_status` from `PENDING` to `REJECTED`). A successful verification is also a synchronization event: the platform appends two `PartnerSyncEvent` rows with `event_type` of `VOLUNTEER_VERIFIED`, one on `channel` `IM` and one on `channel` `IDENTITY_PROVIDER`. A second verification attempt against an already-verified or already-rejected volunteer is rejected with `ERR_INVALID_STATE`.

Background check is a parallel and optional dimension that begins only after identity is `VERIFIED`. The volunteer themselves requests the check, transitioning `background_check_status` from `NONE` to `PENDING`. A request issued before identity reaches `VERIFIED`, or while `background_check_status` is anything other than `NONE`, is rejected with `ERR_INVALID_STATE`. A `SkillAdmin` then resolves a `PENDING` background check either by clearing it (advancing `background_check_status` to `CLEARED`) or by failing it (advancing `background_check_status` to `FAILED`). Both `CLEARED` and `FAILED` are stable: there is no defined transition out of either.

Every volunteer-initiated action against an activity — applying, checking in, checking out, requesting on-leave, or withdrawing — additionally requires `Volunteer.identity_verification_status == VERIFIED`. A volunteer whose identity is not yet `VERIFIED` who attempts any of those five operations is rejected with `ERR_IDENTITY_NOT_VERIFIED`.

A read endpoint exposes a per-volunteer hour breakdown that lists the volunteer's `COMPLETED` applications with their per-application hours and the combined live-plus-archived totals; this read is available to the volunteer themselves and to any `SkillAdmin`, and accepts `limit` and `offset` for pagination.

### 3.2. Skill Catalog and Volunteer Skill Declaration

The skill catalog is curated by `SkillAdmin`. Each `Skill` carries a `code` (unique, 2 to 40 characters, uppercase snake_case), a human-readable `name`, a `requires_certificate` flag (default false) that controls whether a volunteer must attach a proof URL when declaring the skill, and a `sensitivity_level` of either `STANDARD` (default) or `SENSITIVE`. The `sensitivity_level` is the input that drives the activity-level `requires_sensitive_clearance` decision later.

A volunteer self-declares a skill by creating a `VolunteerSkill` row that points at the catalog `skill_id`. If the referenced `Skill.requires_certificate` is true, the declaration must also include a non-null `certificate_url`; if `requires_certificate` is false, the field is optional and may be left null. The new declaration begins in `review_status` `SELF_DECLARED`. A volunteer may not hold two `VolunteerSkill` rows for the same `(volunteer_id, skill_id)` simultaneously in any state other than `REJECTED`; a duplicate attempt is rejected with `ERR_DUPLICATE_SKILL_DECLARATION`.

The volunteer then submits the declaration for review, advancing `review_status` from `SELF_DECLARED` to `UNDER_REVIEW`. Submission requires that the certificate-attachment rule still hold — if `Skill.requires_certificate` is true, the row's `certificate_url` must be non-null at submission; otherwise the submit is rejected with `ERR_INVALID_STATE`. A `SkillAdmin` then either approves the declaration (advancing `review_status` from `UNDER_REVIEW` to `APPROVED` and stamping the acting admin's id into `reviewer_id` and the current server time into `reviewed_at`) or rejects it (advancing `review_status` from `UNDER_REVIEW` to `REJECTED`, also stamping `reviewer_id` and `reviewed_at`); `REJECTED` is terminal.

For a previously-`APPROVED` declaration whose certificate has gone stale, the volunteer may resubmit the row with a refreshed `certificate_url` in the request body; the row reverts from `APPROVED` to `UNDER_REVIEW` for re-review, with the new `certificate_url` overwriting the old.

Only an `APPROVED` `VolunteerSkill` counts as a held skill anywhere else in the platform — in particular, the skill-tag matching at apply time considers no other state.

### 3.3. Activity Authoring, Review, and Time-Gated Lifecycle

An `Organizer` drafts a new `Activity` by supplying its `title` (1 to 120 characters), `description` (1 to 2000 characters), the site coordinates `location_lat` and `location_lng`, the activity time window `start_at` and `end_at`, the recruitment window `recruit_open_at` and `recruit_close_at`, the list of `required_skill_codes` (each entry must resolve to an existing `Skill.code`; the list may be empty), the integer `position_quota` (1 to 1000), an optional `difficulty` of `EASY`, `MEDIUM` (default), or `HARD`, an optional `hour_rule_type` of `ACTUAL_DURATION` (default), `FIXED_VALUE`, or `ROLE_COEFFICIENT`, and — only when `hour_rule_type` is `FIXED_VALUE` — a required `fixed_hour_value` between 0.25 and 24 hours. A draft begins in `status` of `DRAFT` with `Activity.organizer_id` stamped to the acting organizer's id. Calls to define `ActivityRole` rows on a draft activity supply a `role_label` (unique within the activity, 1 to 40 characters) and an optional `coefficient` between 0.5 and 3.0 (default 1.0, two decimal places).

Submission to admin review advances the activity from `DRAFT` to `UNDER_REVIEW`. Submission requires the acting organizer to be the activity's `organizer_id`, `recruit_open_at` to be strictly less than `recruit_close_at`, `recruit_close_at` to be strictly less than `start_at`, `start_at` to be strictly less than `end_at`, every entry in `required_skill_codes` to resolve to an existing `Skill` row, and `position_quota` to be at least 1. Submission also computes and stamps `requires_sensitive_clearance` to true if any skill referenced by `required_skill_codes` has `sensitivity_level` of `SENSITIVE`, false otherwise; this computed flag is what gates the background-check requirement at apply time.

A `SkillAdmin` then approves or rejects the submission. Approval advances `status` from `UNDER_REVIEW` to `PUBLISHED`, mints the activity's six-digit numeric `site_code` (used for on-site check-in), and emits two `PartnerSyncEvent` rows with `event_type` of `ACTIVITY_PUBLISHED` — one on `channel` `PARTNER_ORG` and one on `channel` `IM`. Rejection advances `status` from `UNDER_REVIEW` to `REJECTED`. A rejected activity is not terminal: the original organizer may pull the rejected activity back to `DRAFT` for revision, and the revision-resubmit-review loop may run any number of times.

After publication, the lifecycle is time-gated and driven by the logical clock. When the clock reaches `recruit_open_at`, the activity advances from `PUBLISHED` to `RECRUITING`; when the clock reaches `start_at`, it advances from `RECRUITING` to `RUNNING` (and as a side effect every `Application` for this activity that is still in `APPLIED` is auto-rejected, advancing those rows to `REJECTED`); when the clock reaches `end_at`, it advances from `RUNNING` to `COMPLETED`. The `RUNNING → COMPLETED` transition triggers the cascade described in §2.8: every `Application` still in `CHECKED_IN` with no `check_out_at` has `check_out_at` stamped to `Activity.end_at` and is advanced to `COMPLETED` with full hour and point computation, and every `Application` still in `APPROVED` with no `check_in_at` is advanced to `NO_SHOW`.

An `Organizer` may shelve an activity that has reached `PUBLISHED` or `RECRUITING` if and only if the activity's `filled_positions` is exactly zero — this advances `status` from `PUBLISHED` (or `RECRUITING`) to `SHELVED` and is terminal. A shelve attempt against an activity with one or more filled positions is rejected with `ERR_INVALID_STATE`. An attempt to shelve a `RUNNING` or `COMPLETED` activity is rejected with `ERR_INVALID_STATE`. The terminal states for `Activity` are `COMPLETED`, `REJECTED` (when not pulled back to `DRAFT`), and `SHELVED`; the `REJECTED → DRAFT` revision loop is the one explicit revert path.

A list endpoint returns activities optionally filtered by `status` and `skill_code`, paginated by `limit` and `offset`. A separate ranking endpoint, available to `Organizer` and `SkillAdmin`, returns up to 20 candidate volunteers for an activity ranked by historical-participation score (the count of past `COMPLETED` applications that the candidate has on activities sharing at least one entry of `required_skill_codes` with this one), so that the organizer can proactively reach out to suitable volunteers.

### 3.4. Position Matching, Application, and Approval

A volunteer applies to a `RECRUITING` activity by submitting an application that carries `activity_id` and an optional `activity_role_id`. The server computes `distance_km` at apply time as the great-circle distance between `(home_lat, home_lng)` and `(location_lat, location_lng)`, using the haversine formula on a spherical Earth of mean radius 6371.0088 kilometres: convert each latitude and the differences in latitude and longitude from degrees to radians, take the sine of half the latitude difference squared, plus the cosine of the first latitude times the cosine of the second latitude times the sine of half the longitude difference squared, take the arctangent (two-argument) of the square root of that quantity over the square root of one minus that quantity, multiply by two and by the Earth radius, and round half up to two decimal places. The newly-created `Application` row begins in `status` `APPLIED`.

The application is rejected before creation under any of the following conditions: the volunteer's `identity_verification_status` is not `VERIFIED` (`ERR_IDENTITY_NOT_VERIFIED`); the activity has `requires_sensitive_clearance` of true and the volunteer's `background_check_status` is not `CLEARED` (`ERR_BACKGROUND_CHECK_REQUIRED`); the volunteer does not hold an `APPROVED` `VolunteerSkill` for every entry of `Activity.required_skill_codes` (`ERR_SKILL_MISMATCH`); the activity's `status` is not `RECRUITING`, or the current clock time is outside the half-open recruitment window starting at `recruit_open_at` and ending strictly before `recruit_close_at` (`ERR_RECRUITMENT_CLOSED`); the volunteer already has another non-terminal `Application` (in `APPROVED`, `CHECKED_IN`, `ON_LEAVE`, or `COMPLETED`) on an activity whose time window `[start_at, end_at]` overlaps this activity's window — overlap is evaluated as closed-closed intervals, so an activity that starts at exactly the moment another ends still counts as a conflict and is rejected with `ERR_TIME_CONFLICT`; the computed `distance_km` exceeds 50 kilometres (`ERR_DISTANCE_EXCEEDED`); a non-terminal `Application` of the same `(activity_id, volunteer_id)` already exists (`ERR_DUPLICATE_APPLICATION`); or, when `activity_role_id` is supplied, the referenced `ActivityRole` exists but its `activity_id` does not equal the surrounding activity's id (`ERR_INVALID_REFERENCE`).

Approval of an `APPLIED` application is performed by the activity's `Organizer`. Approval requires the activity to currently be in `RECRUITING` and `Activity.filled_positions` to be strictly less than `Activity.position_quota` at the moment of commit; the same time-conflict check that applied at apply time is re-evaluated at approve time against the volunteer's other non-terminal applications, with the same `ERR_TIME_CONFLICT` outcome. Successful approval advances `Application.status` from `APPLIED` to `APPROVED` and atomically increments `Activity.filled_positions` by exactly 1. Quota saturation at commit time produces `ERR_QUOTA_EXCEEDED`.

Rejection by the same `Organizer` advances an `APPLIED` application to `REJECTED` (terminal). Withdrawal by the volunteer who owns the application has two valid forms: an `APPLIED` application withdraws to `WITHDRAWN` unconditionally; an `APPROVED` application may be withdrawn by the volunteer only while the parent activity is still `RECRUITING`, and the withdrawal additionally decrements `Activity.filled_positions` by exactly 1 to free the slot. A withdraw attempt on an `APPROVED` application after the parent activity has progressed past `RECRUITING` is rejected with `ERR_INVALID_STATE`.

### 3.5. On-Site Check-In, Leave, and Check-Out

Once the parent activity reaches `RUNNING`, the volunteer who holds an `APPROVED` application checks in. Check-in offers two independent proofs of presence and accepts either: the volunteer may submit a `site_code` value in the request body that matches the activity's minted `site_code`, or the volunteer may submit `check_in_lat` and `check_in_lng` whose haversine distance to `(location_lat, location_lng)` is at most 0.50 kilometres (500 metres). Lacking either valid proof, the attempt is rejected with `ERR_CHECK_IN_PROOF_FAILED`. Successful check-in advances `Application.status` from `APPROVED` to `CHECKED_IN`, stamps `check_in_at` to the current server time, and — if `check_in_at` is later than `Activity.start_at` plus 15 minutes — sets `late_marker` to true. The `late_marker` is informational only and never reduces credited hours.

A `CHECKED_IN` volunteer who must temporarily leave during a `RUNNING` activity submits a leave request with a `leave_reason` of 1 to 500 characters; this advances the application from `CHECKED_IN` to `ON_LEAVE`. A leave request without a non-empty `leave_reason`, or against an application not currently in `CHECKED_IN`, or while the parent activity is not `RUNNING`, is rejected.

Check-out by a `CHECKED_IN` volunteer (the parent activity must still be in `RUNNING`) advances `Application.status` from `CHECKED_IN` to `COMPLETED` and stamps `check_out_at` to the current server time. If `check_out_at` is earlier than `Activity.end_at` minus 15 minutes, `early_departure_marker` is set to true. The check-out also runs the service-hour calculation and the point-earning calculation in that order, and writes their results into `Application.credited_hours`, `Application.adjusted_hours`, and `Application.points_awarded`. As the same logical transaction, `Volunteer.total_completed_activities` is incremented by 1, `Volunteer.total_service_hours` is increased by the freshly-computed `Application.adjusted_hours`, and `Volunteer.points_balance` is increased by the freshly-computed `Application.points_awarded`.

The `Organizer` may apply a manual correction to `check_in_at`, `check_out_at`, `late_marker`, or `early_departure_marker` on an existing application; the request body carries any subset of those four fields. If the application's `status` is `COMPLETED` at correction time, the service-hour calculation is re-run and the delta in `Application.adjusted_hours` propagates to `Volunteer.total_service_hours` immediately (an upward correction adds; a downward correction subtracts). Every manual correction also appends an `AuditLog` row with `action_type` of `HOUR_ADJUST_REQUEST`, `actor_role` of `Organizer`, `actor_id` set to `X-User-ID`, `target_entity` set to the string identifying the application, `target_id` set to the application's id, and `payload` capturing the before/after values of the touched fields.

### 3.6. Service-Hour Calculation

Credited hours for a single completed `Application` are computed in a strictly pinned order, and the calculation depends on the parent `Activity.hour_rule_type`.

The first step computes raw hours per branch. When `hour_rule_type` is `ACTUAL_DURATION`, raw hours equal the elapsed time from `check_in_at` to `check_out_at` expressed in hours (the difference in seconds divided by 3600). When `hour_rule_type` is `FIXED_VALUE`, raw hours equal the parent activity's `fixed_hour_value` verbatim regardless of how long the volunteer was actually present — a 30-minute attendance still credits the full fixed value. When `hour_rule_type` is `ROLE_COEFFICIENT`, raw hours equal the elapsed hours from `check_in_at` to `check_out_at` multiplied by the assigned `ActivityRole.coefficient`, so the same elapsed time produces different hours for a higher-coefficient role than for a lower-coefficient one.

The second step applies a leave penalty: if `Application.leave_reason` is non-null at any point in the application's history (that is, the application reached `ON_LEAVE` at some point), raw hours are multiplied by 0.50. This is the heaviest penalty and dominates over the early-departure penalty.

The third step applies an early-departure penalty: if `Application.early_departure_marker` is true and the leave penalty did not already fire (i.e., `leave_reason` is null), the result is multiplied by 0.75 instead. A leave penalty already paid means the early-departure penalty does not additionally apply — the two are mutually exclusive in this order.

The fourth step rounds the result half up to two decimal places. The rounded value is written into `Application.credited_hours`. `Application.adjusted_hours` is set to the same value at this initial computation and mirrors `credited_hours` until and unless an approved `HourAdjustment` delta is later applied.

The same calculation runs both on a volunteer-initiated check-out and on the system's automatic completion when the parent activity advances from `RUNNING` to `COMPLETED` for any application still in `CHECKED_IN`. The 15-minute thresholds that decide `late_marker` and `early_departure_marker` are independent: 15 minutes past `start_at` for the late marker, 15 minutes before `end_at` for the early-departure marker.

### 3.7. Point Earning, Hour Adjustments, and the Point Mall

Points awarded on a completed application are computed in a strictly pinned order using the same multiplier set described below.

First, a base value is computed as `Application.adjusted_hours` multiplied by 10 (the hours-to-points factor) and rounded half up to exactly two decimal places. Second, a difficulty multiplier is taken from the parent `Activity.difficulty`: `EASY` maps to 1.00, `MEDIUM` to 1.50, and `HARD` to 2.00. Third, a role multiplier is taken from the assigned `ActivityRole.role_label` (this is the label string, not the numeric `coefficient`): `LEAD` maps to 1.20, `SUPPORT` to 1.00, and `REGULAR` to 0.90; if no `ActivityRole` is assigned to the application, the role multiplier is 1.00. Fourth, the raw point value is the base times the difficulty multiplier times the role multiplier. Fifth, the integer `Application.points_awarded` is the floor of that raw value — always rounded down to an integer, never half up. The two-decimal rounding on the base happens before the multipliers are applied; the floor on the final value happens after. Both rules are part of the canonical evaluation order and reordering them is not equivalent.

This calculation runs in two situations. On a first-time completion (whether volunteer-initiated check-out or automatic completion at activity end), the freshly-computed value is written into `Application.points_awarded` and the volunteer's `points_balance` is increased by the full amount. When an approved `HourAdjustment` later changes `Application.adjusted_hours`, the calculation re-runs with the updated `adjusted_hours`; the volunteer's `points_balance` is then incremented (or decremented) only by the delta between the new and old `points_awarded`, never by the full new amount. The new value overwrites `Application.points_awarded`.

`HourAdjustment` itself is the formal mechanism by which an organizer requests a correction to a completed application's hours after the fact. The `Organizer` files an adjustment with the target `application_id`, a signed `delta_hours` between -8.00 and +8.00 hours (two decimals, non-zero), and a `reason` string of 10 to 500 characters. Filing requires the parent `Application` to currently be in `COMPLETED` and the resulting `Application.adjusted_hours + delta_hours` to be greater than or equal to zero — a delta that would drive adjusted hours negative is rejected with `ERR_NEGATIVE_HOURS`. The new `HourAdjustment` row begins in `status` of `PENDING` and writes the acting organizer's id into `requested_by_id`. Filing also appends an `AuditLog` with `action_type` of `HOUR_ADJUST_REQUEST`.

A `SkillAdmin` then approves or rejects the pending adjustment. Approval re-checks the non-negativity rule and is rejected with `ERR_NEGATIVE_HOURS` if the sum has shifted in the meantime to violate it; on success it advances `HourAdjustment.status` from `PENDING` to `APPROVED`, stamps `approver_id` and `decided_at`, captures the application's old `adjusted_hours`, sets the new `Application.adjusted_hours` to the old value plus `delta_hours`, captures the application's old `points_awarded`, recomputes `Application.points_awarded` against the new `adjusted_hours`, increases `Volunteer.total_service_hours` by the hours delta, and increases `Volunteer.points_balance` by the points delta. The `AuditLog` row appended on approval has `action_type` of `HOUR_ADJUST_APPROVE` and a `payload` that includes both old and new values for `adjusted_hours` and `points_awarded`. Rejection advances `HourAdjustment.status` from `PENDING` to `REJECTED`, stamps `approver_id` and `decided_at`, and appends an `AuditLog` with `action_type` of `HOUR_ADJUST_REJECT`. Both `APPROVED` and `REJECTED` are terminal.

The point mall is the destination for redeeming earned points. A `SkillAdmin` creates a `PointMallItem` with a unique `sku` (2 to 40 characters), a display `name`, a `point_cost` between 1 and 100000, and an initial `stock`. Items begin in `status` of `ACTIVE`. A `SkillAdmin` may restock an `OUT_OF_STOCK` item by supplying a positive `delta`, which increases `stock` by `delta` and advances `status` back to `ACTIVE`; a non-positive `delta` is rejected. A `SkillAdmin` may archive an item from either `ACTIVE` or `OUT_OF_STOCK`, advancing `status` to `ARCHIVED`; `ARCHIVED` is terminal.

A volunteer creates a `RedemptionOrder` against an `ACTIVE` `PointMallItem` by supplying the `item_id` and a `quantity` between 1 and 10. The server snapshots `total_points` as `PointMallItem.point_cost` multiplied by `quantity` at creation, and stores the order in `status` of `PENDING`. Order creation also requires that the item's current `stock` be at least `quantity` (otherwise `ERR_INSUFFICIENT_STOCK`) and that the volunteer's current `points_balance` be at least `total_points` (otherwise `ERR_INSUFFICIENT_POINTS`). A `SkillAdmin` then fulfills a `PENDING` order; fulfillment requires the item to still be in `ACTIVE`, `PointMallItem.stock` to be at least `quantity`, and `Volunteer.points_balance` to be at least `total_points` (re-checked at fulfillment time, since either side may have shifted), and atomically decrements `PointMallItem.stock` by `quantity`, decrements `Volunteer.points_balance` by `total_points`, and advances `RedemptionOrder.status` to `FULFILLED`. If the post-fulfillment `PointMallItem.stock` reaches zero, the parent item cascades from `ACTIVE` to `OUT_OF_STOCK`. The volunteer who owns a `PENDING` order may cancel it, advancing `status` to `CANCELLED` (terminal); cancellation does not touch stock or points because nothing was deducted yet.

### 3.8. Hour Archival and Point Expiration

Two scheduled sweeps run every time the logical clock advances, and both consume rows from the application history.

The hours-archival sweep finds every `Application` in `COMPLETED` whose `check_out_at` is more than 365 days in the past — comparison is strictly greater than (an application whose check-out was exactly 365 days ago does not yet archive). For each such application, the volunteer's `total_service_hours` is decreased by the application's `adjusted_hours` and `archived_hours` is increased by the same amount. The `Application.adjusted_hours` field itself is not modified, and lifetime hours can always be recovered as `total_service_hours + archived_hours`. Critically, certificate eligibility consults only `total_service_hours` (the live, non-archived total) and not `archived_hours`, so archived hours can no longer be used to qualify for new certificate issuance, even though they remain visible in the lifetime total. Already-issued certificates are unaffected — their `hours_at_issuance` snapshot stands.

The points-expiration sweep finds every `Application.points_awarded` earned at an `Application.check_out_at` more than 730 days in the past — again strictly greater than (a check-out exactly 730 days ago has not yet expired). The platform maintains a per-application running ledger of unspent points: redemptions consume the volunteer's points first-in-first-out by ascending `check_out_at` (with smaller `Application.id` as the tie-break when two applications share the same `check_out_at`); whatever remains unspent on a given application past the cutoff is removed from `Volunteer.points_balance`. Once expired, the points are gone — a subsequent `HourAdjustment` that recomputes `Application.points_awarded` for an already-expired application does not resurrect the original points, but its delta does still apply to the current balance, clamped at zero (a delta that would drive `points_balance` below zero is clamped, and an audit entry is recorded). The newly-minted delta points reset the 730-day clock for the delta only; the originally-expired portion stays expired.

### 3.9. Certificate Issuance and Verification

Certificate templates are curated by `SkillAdmin`. Each `CertificateTemplate` carries a unique `code` (2 to 40 characters), a display `title`, a `min_hours` threshold (greater than 0, two decimal places) on the volunteer's `total_service_hours`, and a `min_completed_activities` threshold (at least 1) on the volunteer's `total_completed_activities`. Templates begin in `status` of `ACTIVE` and may move to `ARCHIVED`.

A `SkillAdmin` issues a single certificate by supplying `template_id` and `volunteer_id`. Eligibility is satisfied when both predicates hold simultaneously: the volunteer's `total_service_hours` is greater than or equal to the template's `min_hours`, and the volunteer's `total_completed_activities` is greater than or equal to the template's `min_completed_activities`. Both comparisons are inclusive — a volunteer with exactly `min_hours` and exactly `min_completed_activities` is eligible; a volunteer 0.01 hours below `min_hours` is not, and the issuance is rejected with `ERR_NOT_ELIGIBLE`. The eligibility computation consults only live `total_service_hours`, never `archived_hours`. Additionally, no certificate of the same `(volunteer_id, template_id)` may already exist in a state other than `REISSUED` or `REVOKED`; an attempted re-issuance into a slot that is already occupied is rejected with `ERR_CERTIFICATE_ALREADY_ISSUED`.

A successful single issuance creates a new `Certificate` row with the supplied `template_id` and `volunteer_id`, mints a unique 12-character alphanumeric `serial_number`, snapshots the volunteer's current `total_service_hours` into `hours_at_issuance` and `total_completed_activities` into `activities_at_issuance`, and starts the row in `status` of `ISSUED`. Issuance also appends an `AuditLog` with `action_type` of `CERTIFICATE_ISSUE` and emits a `PartnerSyncEvent` on `channel` `PARTNER_ORG` with `event_type` of `CERTIFICATE_ISSUED`.

Batch issuance accepts a single `template_id` plus a `volunteer_ids` list. The server performs the eligibility check independently per volunteer in the list; eligible volunteers are issued exactly as in the single-issue flow (each producing its own `Certificate`, `AuditLog` row, and `PartnerSyncEvent`); ineligible volunteers are skipped and reported with a reason. The batch response is a partial-success object listing the issued and the skipped subsets — the request as a whole succeeds at HTTP 200 even when some volunteers were skipped.

A `SkillAdmin` may reissue an `ISSUED` certificate (for instance, when the original was lost). Reissuance creates a new `Certificate` row carrying the same `template_id` and `volunteer_id`, a fresh `serial_number`, and refreshed `hours_at_issuance` and `activities_at_issuance` snapshots taken from the volunteer's current totals, with the new row in `status` of `ISSUED`. The original certificate's `status` is moved from `ISSUED` to `REISSUED`, and its `replacement_serial_number` is set to point at the new row's `serial_number`. An `AuditLog` row with `action_type` of `CERTIFICATE_REISSUE` is appended; its `payload` includes the new certificate's `serial_number`. A `SkillAdmin` may also revoke an `ISSUED` certificate, advancing `status` to `REVOKED` (terminal) and appending an `AuditLog` row with `action_type` of `CERTIFICATE_REVOKE`. Once a certificate has reached `REISSUED` or `REVOKED`, no further state changes apply to that row.

A public-verification capability — accessible to all three roles — looks up a certificate by its `serial_number` (taken as a path parameter) and returns the row, including its current `status`. Verification of a `REISSUED` certificate exposes the `replacement_serial_number` so a holder of an outdated certificate can locate its replacement.

## 4. Endpoint Definitions

The full canonical paths appear in the table below. New resource creation responds with HTTP 201; modifications, state-machine transitions, list reads, and single-resource reads respond with HTTP 200. Request and response bodies follow the envelope defined in §2.2; the table intentionally omits the request and response bodies — readers reconstruct those from the §3 narrative.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /volunteers | Register a new volunteer in PENDING identity status | SkillAdmin |
| GET | /volunteers/{id} | Read a volunteer including computed totals | Volunteer, Organizer, SkillAdmin |
| POST | /volunteers/{id}/identity:verify | SkillAdmin marks identity verified | SkillAdmin |
| POST | /volunteers/{id}/identity:reject | SkillAdmin rejects identity | SkillAdmin |
| POST | /volunteers/{id}/background-check:request | Volunteer requests background check | Volunteer |
| POST | /volunteers/{id}/background-check:clear | SkillAdmin clears background check | SkillAdmin |
| POST | /volunteers/{id}/background-check:fail | SkillAdmin fails background check | SkillAdmin |
| GET | /volunteers/{id}/hours | List COMPLETED Applications with hour breakdown (live + archived totals) | Volunteer, SkillAdmin |
| POST | /skills | Register a skill in the catalog | SkillAdmin |
| GET | /skills | List skills | Volunteer, Organizer, SkillAdmin |
| POST | /volunteer-skills | Volunteer declares a skill (SELF_DECLARED) with optional certificate URL | Volunteer |
| POST | /volunteer-skills/{id}/submit | Volunteer submits declaration to admin review | Volunteer |
| POST | /volunteer-skills/{id}/approve | SkillAdmin approves declaration | SkillAdmin |
| POST | /volunteer-skills/{id}/reject | SkillAdmin rejects declaration | SkillAdmin |
| POST | /volunteer-skills/{id}/resubmit | Volunteer re-submits APPROVED declaration after cert URL refresh | Volunteer |
| POST | /activities | Organizer creates a draft activity | Organizer |
| POST | /activities/{id}/submit | Organizer submits draft for admin review | Organizer |
| POST | /activities/{id}/approve | SkillAdmin approves and publishes (mints site_code, emits 2 sync events) | SkillAdmin |
| POST | /activities/{id}/reject | SkillAdmin rejects (revisable via /revise) | SkillAdmin |
| POST | /activities/{id}/revise | Organizer pulls a REJECTED activity back to DRAFT | Organizer |
| POST | /activities/{id}/shelve | Organizer shelves a PUBLISHED or RECRUITING activity (only when filled_positions == 0) | Organizer |
| GET | /activities/{id} | Read activity (including filled_positions, requires_sensitive_clearance, site_code if RUNNING) | Volunteer, Organizer, SkillAdmin |
| GET | /activities | List activities, filterable by status and skill_code | Volunteer, Organizer, SkillAdmin |
| POST | /activities/{id}/roles | Organizer defines an ActivityRole | Organizer |
| GET | /activities/{id}/recommended-volunteers | Rank approved volunteers for this Activity by historical-participation score (returns up to 20) | Organizer, SkillAdmin |
| POST | /applications | Volunteer applies; computes distance_km | Volunteer |
| POST | /applications/{id}/approve | Organizer approves; increments Activity.filled_positions | Organizer |
| POST | /applications/{id}/reject | Organizer rejects | Organizer |
| POST | /applications/{id}/withdraw | Volunteer withdraws (APPLIED or APPROVED while RECRUITING) | Volunteer |
| POST | /applications/{id}/check-in | Volunteer checks in via site_code or GPS; sets check_in_at, late_marker | Volunteer |
| POST | /applications/{id}/leave | Volunteer requests on-leave during a running activity | Volunteer |
| POST | /applications/{id}/check-out | Volunteer checks out; runs hour and point calculations and updates Volunteer totals | Volunteer |
| POST | /applications/{id}/manual-correction | Organizer manually fixes check_in_at, check_out_at, or markers (records AuditLog) | Organizer |
| GET | /applications/{id} | Read application | Volunteer, Organizer, SkillAdmin |
| POST | /hour-adjustments | Organizer files a delta on an existing COMPLETED Application | Organizer |
| POST | /hour-adjustments/{id}/approve | SkillAdmin approves; mutates adjusted_hours and recomputes points; appends AuditLog | SkillAdmin |
| POST | /hour-adjustments/{id}/reject | SkillAdmin rejects | SkillAdmin |
| POST | /point-mall-items | SkillAdmin creates item | SkillAdmin |
| POST | /point-mall-items/{id}/restock | SkillAdmin restocks (delta > 0) | SkillAdmin |
| POST | /point-mall-items/{id}/archive | SkillAdmin archives | SkillAdmin |
| GET | /point-mall-items | List items | Volunteer, SkillAdmin |
| POST | /redemption-orders | Volunteer creates a redemption order (snapshots total_points) | Volunteer |
| POST | /redemption-orders/{id}/fulfill | SkillAdmin fulfills; deducts stock and points | SkillAdmin |
| POST | /redemption-orders/{id}/cancel | Volunteer cancels a PENDING order | Volunteer |
| POST | /certificate-templates | SkillAdmin creates template | SkillAdmin |
| POST | /certificates | SkillAdmin issues a single certificate | SkillAdmin |
| POST | /certificates/batch | SkillAdmin issues a template to many volunteers (partial-success) | SkillAdmin |
| POST | /certificates/{id}/reissue | SkillAdmin reissues (creates new, marks old REISSUED) | SkillAdmin |
| POST | /certificates/{id}/revoke | SkillAdmin revokes | SkillAdmin |
| GET | /certificates/verify/{serial_number} | Public-verification by serial_number | Volunteer, Organizer, SkillAdmin |
| GET | /audit-logs | List AuditLog entries (filter by action_type, target_entity, target_id) | SkillAdmin |
| GET | /partner-sync-events | List PartnerSyncEvent entries (filter by channel, event_type) | SkillAdmin |
| POST | /_clock/advance | Test harness — advance server clock to a target_time; runs due transitions and sweeps | SkillAdmin |
| GET | /_clock | Read current server clock | Volunteer, Organizer, SkillAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_IDENTITY_NOT_VERIFIED | 403 |
| ERR_BACKGROUND_CHECK_REQUIRED | 403 |
| ERR_SKILL_MISMATCH | 422 |
| ERR_RECRUITMENT_CLOSED | 409 |
| ERR_TIME_CONFLICT | 409 |
| ERR_DISTANCE_EXCEEDED | 422 |
| ERR_DUPLICATE_SKILL_DECLARATION | 409 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_QUOTA_EXCEEDED | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_INSUFFICIENT_POINTS | 409 |
| ERR_NEGATIVE_HOURS | 422 |
| ERR_NOT_ELIGIBLE | 422 |
| ERR_CERTIFICATE_ALREADY_ISSUED | 409 |
| ERR_CHECK_IN_PROOF_FAILED | 422 |
| ERR_INVALID_INPUT | 422 |
| ERR_VERSION_CONFLICT | 409 |
