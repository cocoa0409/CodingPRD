# Afterschool Camp Registration API — Product Requirements Document

## 1. Introduction

Schools and community recreation centers operate two adjacent product lines that share staff, facilities, and families but diverge in cadence: weekly after-school programs running across a term, and block-scheduled summer camp weeks. The Afterschool Camp Registration API consolidates intake, parental authorization, weekly seat allocation, scholarship awarding, and rainy-day rerouting into a single back office. Every household, child, guardian, emergency contact, and parental permission lives behind the same envelope so that program administrators and parents see a consistent surface, even though the underlying lifecycle for a session is meaningfully different from the lifecycle for an individual enrollment.

The system is designed around three persistent tensions: limited weekly capacity (which forces waitlisting and a deterministic promotion order when seats free up), parental safety obligations (which require active medical and pickup authorizations plus at least one named emergency contact before any child may attend), and tiered financial assistance (sibling discounts and scholarship awards that interact in a fixed, snapshotted order). This document is the engineering specification for the REST API that mediates those tensions. It is written for an implementer who has no prior context on the camp domain and treats every threshold, ordering, and rounding rule as load-bearing.

Throughout, dollar amounts are tracked in integer cents to avoid floating-point drift, time-of-day references are anchored to a server-controlled logical clock (advanced via an explicit admin endpoint rather than wall-clock time), and every business rule that could plausibly admit two interpretations is pinned to one. The intent is that two engineers reading this document independently will arrive at the same set of behaviors down to error code, transition target, and rounding direction.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-Role` and `X-User-ID`. If either header is missing or blank, the request is rejected with `ERR_AUTH_REQUIRED` and HTTP status 401. If the role on the request is not authorized for the endpoint being called (per the RBAC mapping summarized in §4), the request is rejected with `ERR_FORBIDDEN` and HTTP status 403.

Two roles are defined, with the exact spellings `ProgramAdmin` and `Guardian`. A `ProgramAdmin` is camp staff — an administrator who can manage sessions, scholarships, weather posture, and family records belonging to any household. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server treats it as an audit token and does not compare it to any entity's `id`. A `Guardian` is a parent or legal guardian operating on behalf of children in their own family. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian` row; ownership checks on any resource that references a `Guardian` (and, by extension, the `Family` to which that `Guardian` belongs) compare the resource's family lineage to the family of the `Guardian` whose `id` matches `X-User-ID`.

Cross-family access by a `Guardian` is forbidden. When a `Guardian` attempts to operate on a `Child`, `EmergencyContact`, `Authorization`, or `Enrollment` that does not roll up to their own `Family`, the request is rejected with `ERR_FAMILY_MISMATCH` and HTTP status 403. This includes the case where the `Guardian` references a `guardian_id` on a new `Authorization` that belongs to a different family than the target child.

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0. Both are integers. List results are sorted by `created_at` ascending. List responses additionally populate `total_count` (the unbounded count of rows matching the filter set) and `has_more` (true when more rows exist beyond the current window) inside `meta`.

### 2.4. Common Resource Properties and Versioning

Every entity that participates in update workflows — `Family`, `Guardian`, `Child`, `EmergencyContact`, `Session`, `Enrollment`, `ScholarshipAward` — carries four system-managed properties: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. Timestamps `created_at` and `updated_at` are ISO 8601 UTC strings with three fractional digits. The `version` is a positive integer that starts at 1 on creation and increments by exactly 1 on every persisted mutation of that row, including mutations driven by side-effect cascades rather than direct PATCH calls. Whenever a row's `version` increments, its `updated_at` is refreshed to the current logical clock.

Two entities are leaner. `Authorization` and `SessionDay` carry only `id` and `created_at` — both `updated_at` and `version` are absent on these rows. The state transitions on these entities are recorded directly in their `status` or `weather_status` fields, and concurrency on them is governed by the rules in §2.6 rather than by an OCC `version` check.

### 2.5. Optimistic Concurrency Control

Endpoints that mutate `common_fields=true` entities accept an optional `version` field in the request body. When the client supplies `version` and it matches the current persisted `version` of the target row, the mutation proceeds and the resulting row's `version` is incremented by one. When the client supplies `version` and it does not match, the mutation is rejected with `ERR_STALE_VERSION` and HTTP status 409. When the client omits `version` from the body entirely, no concurrency check is performed and the mutation proceeds as if the client had supplied the current value. A `PATCH` on `Family` that fails OCC reports the same `ERR_STALE_VERSION` to the loser.

### 2.6. Nested Resource Resolution and Path Parameters

Several resources are nested: guardians, children, scholarships, and the family-invoice view all live under a `Family`; emergency contacts and authorizations live under a `Child`; rosters and weather days hang off a `Session`. Path parameter resolution is left-to-right: the family is resolved first, then the child, then the session, then the enrollment, the authorization, the scholarship, the session day, or the emergency contact. The first parameter that fails to resolve causes the request to be rejected with `ERR_RESOURCE_NOT_FOUND` and HTTP status 404. This left-to-right ordering means that a request for an existing child under a non-existent family fails at the family hop, not the child hop.

### 2.7. The Logical Clock

The server keeps a single monotonic logical clock used for all temporal evaluations (authorization expiry, week-window comparisons, session-day weather posture, child age computation against `Session.reference_date`). The clock is advanced by an admin-only test-driving capability that takes an `iso_timestamp` and atomically (a) sweeps every `Authorization` with `status` `ACTIVE` whose `expires_at` is at or before the new instant into the `EXPIRED` state, and (b) re-projects `medical_authorization_status` and `pickup_authorization_status` onto every affected `Child` per the projection rules in §2.8. Wall-clock time is not consulted anywhere else in the system.

### 2.8. Authorization State Projection

On every read of a `Child`, on every `Authorization` status transition, and at the end of a clock-advance sweep, the system recomputes the two derived authorization statuses on the child. For each kind in the set `MEDICAL` and `PICKUP` independently: the status is `ACTIVE` if there exists at least one `Authorization` belonging to that child with that `kind`, with `status` equal to `ACTIVE`, whose `effective_at` is at or before the current clock and whose `expires_at` is strictly after the current clock; the status is `EXPIRED` if no such currently-active row exists but at least one `Authorization` of that kind has ever existed for the child; and the status is `NONE` if no `Authorization` of that kind has ever been recorded for the child. The two derived fields `medical_authorization_status` and `pickup_authorization_status` are independent — a child may be `ACTIVE` for one kind and `EXPIRED` for the other.

### 2.9. Validation Precedence

When multiple validations could fire on the same request, the system evaluates them in a fixed order so the caller sees a deterministic error. Authentication is checked first — the presence and shape of `X-User-Role` and `X-User-ID`, both surfacing as `ERR_AUTH_REQUIRED`, before role authorization is evaluated and `ERR_FORBIDDEN` is returned. Path-parameter existence is checked next, returning `ERR_RESOURCE_NOT_FOUND`. Then family-scope ownership is checked for guardian-driven endpoints, returning `ERR_FAMILY_MISMATCH`. The three confirmation safety checks — active medical authorization, active pickup authorization, and at least one emergency contact — are evaluated in that order against confirmation requests, surfacing `ERR_MEDICAL_AUTH_REQUIRED`, then `ERR_PICKUP_AUTH_REQUIRED`, then `ERR_EMERGENCY_CONTACT_REQUIRED`. After the safety checks, state-machine legality (`ERR_INVALID_STATE`) is evaluated before domain constraints such as age (`ERR_AGE_OUT_OF_RANGE`), week-index window (`ERR_INVALID_WEEK_INDEX`), authorization time range (`ERR_INVALID_TIME_RANGE`), emergency-contact uniqueness (`ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN`), and capacity / duplicate enrollment (`ERR_DUPLICATE_ENROLLMENT`). Scholarship-eligibility (`ERR_SCHOLARSHIP_INELIGIBLE`) and the diagnostic rainy-pool sufficiency (`ERR_RAINY_POOL_EXHAUSTED`) sit alongside the constraint band. Body-shape validation (`ERR_VALIDATION`, HTTP 400) is treated as a structural prerequisite — when the request body fails type, required-field, or integer-range validation against the declared field constraints, the system rejects with `ERR_VALIDATION` before any of the deeper business checks have a chance to evaluate; OCC (`ERR_STALE_VERSION`) is also evaluated as part of the constraint band on PATCH endpoints. Family soft-delete blocking (`ERR_FAMILY_HAS_FUTURE_ENROLLMENTS`) applies only to family deletion.

### 2.10. Money, Rounding, and Snapshot Discipline

Every monetary amount in the system is an integer count of cents. `Session.base_weekly_fee_cents` and `ScholarshipAward.total_credit_cents` are caller-supplied non-negative integers (scholarship credit must be at least 1). All discount computations that involve a percentage tier — currently only the sibling discount — round half-up to the nearest whole cent per line item, independently, before any family-level summation; the implementation must never sum un-rounded per-line discounts and then round the sum. Scholarship allocation is always integer-cents from the start and therefore does not round.

A second discipline applies to discount values: at the moment an `Enrollment` transitions into `CONFIRMED`, the chosen `list_fee_cents`, `sibling_discount_cents`, `scholarship_discount_cents`, and `final_fee_cents` are snapshotted onto the enrollment row and become immutable on that row except for the explicit cascades documented in §3. A later change to the sibling count, a later scholarship grant, or a later revocation does not retroactively rewrite a confirmed row's snapshotted figures — the only way an existing snapshot changes is via the explicit recompute that runs on confirmed-sibling cancellation (which may raise a remaining sibling's `sibling_discount_cents` downward as the family count shrinks) or via cancellation refund of a scholarship award.

### 2.11. Capacity, Waitlisting, and Cascading Consistency

A `Session` exposes a per-week seat ceiling via `weekly_capacity`, and the system maintains `outdoor_headcount` and `rainy_day_used` on each `SessionDay` so that staff can see attendance posture at a glance. Capacity is enforced with a strict inequality: a new confirmation is allowed when the count of currently-`CONFIRMED` enrollments for the target `(session_id, week_index)` is strictly less than `Session.weekly_capacity`. When the count equals capacity, the enrollment goes to the waitlist with a queue position rather than failing. Direct races on the last seat — two simultaneous confirmations against the last open slot — are serialized first-writer-wins on the per-week capacity counter, and the losing request is rejected with `ERR_WEEKLY_CAPACITY_FULL` (HTTP 409). This is the only path that produces that error; the normal-path "capacity is at ceiling" outcome is `WAITLISTED`, not an error.

Cascades downstream of any state change refresh `updated_at` and increment `version` on every row they touch on `common_fields=true` entities, even when the cascade fires from a parent transition rather than from a direct caller. An enrollment whose `sibling_discount_cents` is recomputed because a peer cancelled, for example, sees its `version` advance and its `updated_at` move forward.

### 2.12. State Enumerations

For ease of reference, the discrete states that appear throughout the rest of this document use exact uppercase strings. A `Session` is in one of `DRAFT`, `OPEN`, `CLOSED`, or `CANCELLED`. An `Enrollment` is in one of `PENDING_AUTH`, `CONFIRMED`, `WAITLISTED`, `CANCELLED`, or `COMPLETED`. An `Authorization` is in one of `ACTIVE`, `EXPIRED`, or `REVOKED`. A `ScholarshipAward` is in one of `ACTIVE`, `EXHAUSTED`, or `REVOKED`. A `SessionDay` has a `weather_status` of `NORMAL`, `RAINY`, or `CLOSED`. A `Family` has a `residency_status` of `STANDARD`, `IN_DISTRICT`, or `OUT_OF_DISTRICT` (default `STANDARD`). A `Guardian.relationship` is `PARENT`, `STEP_PARENT`, `LEGAL_GUARDIAN`, or `OTHER`. A `Child.medical_authorization_status` and `Child.pickup_authorization_status` are each one of `NONE`, `ACTIVE`, or `EXPIRED` (defaulting to `NONE` when no authorization has ever been issued). A `Session.kind` is `AFTERSCHOOL` or `SUMMER_CAMP`. A `ScholarshipAward.granted_for_kind` is one of `AFTERSCHOOL`, `SUMMER_CAMP`, or `ANY`. An `Authorization.kind` is `MEDICAL` or `PICKUP`.

## 3. Business Logic & Workflows

### 3.1. Household Setup: Family, Guardians, and Children

Every camp engagement is rooted in a `Family` household. A `ProgramAdmin` creates a family with a display `household_name` (1–100 characters) and a `primary_email` that is lower-cased on intake and must be unique across all non-archived families. The optional `residency_status` defaults to `STANDARD` when omitted; admins choose `IN_DISTRICT` or `OUT_OF_DISTRICT` when residency drives downstream scholarship eligibility decisions. The `archived` flag is system-managed and starts at false; once a family is soft-deleted, it is true, and the household can no longer enroll new children.

Guardians are added under the family by either a `ProgramAdmin` or a `Guardian` already attached to that family. A guardian record carries a `full_name` (1–100 characters), a `phone` in E.164-style notation between 8 and 20 characters, and a `relationship` value chosen from `PARENT`, `STEP_PARENT`, `LEGAL_GUARDIAN`, or `OTHER`. Each family has exactly one primary contact at any time — the row whose `is_primary` is true. When a new guardian is created with `is_primary` set to true, any previously primary guardian on the same family is silently demoted to `is_primary` false, and only the newly added record is left as the family's primary; the demotion increments the demoted row's `version` and refreshes its `updated_at`. If the request omits `is_primary`, the new guardian defaults to non-primary.

Children are likewise registered under the family by either a `ProgramAdmin` or a same-family `Guardian`. A child record requires `full_name` (1–100 characters) and `date_of_birth` (ISO 8601 calendar date in `YYYY-MM-DD`), which must lie strictly in the past relative to the current logical clock. The child's `medical_authorization_status`, `pickup_authorization_status`, and `emergency_contact_count` are derived: they start at `NONE`, `NONE`, and 0 respectively and are recomputed whenever the underlying authorization or contact rows change or the clock advances. Reading a child always returns the freshly projected statuses and the live contact count.

Updates to a family by a `ProgramAdmin` may revise `household_name`, `primary_email`, or `residency_status`, and the modification request must carry the current `version` in the body to clear the OCC check. A family soft-delete by a `ProgramAdmin` flips `archived` to true. Soft-delete is refused with `ERR_FAMILY_HAS_FUTURE_ENROLLMENTS` whenever any `Enrollment` belonging to this family is currently `CONFIRMED` against a session week whose calendar window (`Session.week_start` plus seven days multiplied by `Enrollment.week_index`) is strictly after the logical clock; the family must first cancel or wait out those enrollments.

### 3.2. Emergency Contacts and Parental Authorizations

A child cannot be enrolled and confirmed into a session without at least one emergency contact and active medical and pickup authorizations. The system surfaces these prerequisites both through the derived fields on the `Child` row and through the validation chain at confirmation time.

An emergency contact carries `full_name` (1–100 characters), an E.164-style `phone` between 8 and 20 characters, a free-text `relationship` label (1–60 characters, accepting strings such as "aunt" or "neighbor"), and an integer `priority` between 1 and 9 inclusive that determines call order — lower numbers are called first. Each `(child_id, priority)` pair must be unique among the child's non-archived contacts; an attempt to add a contact at a priority that is already in use is rejected with `ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN`. Two callers racing to insert the same priority for the same child are serialized first-writer-wins on `(child_id, priority)`, and the loser receives the same `ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN` (HTTP 409). The system enforces at most nine non-archived contacts per child via this priority window. Adding a contact increments `Child.emergency_contact_count`; archiving a contact via deletion decrements it. The `archived` flag on a contact is system-managed; archived rows do not count toward the limit.

A parental authorization is created by either a `ProgramAdmin` or a same-family `Guardian` and carries: a `guardian_id` pointing at the guardian granting the permission (who must belong to the same family as the child, otherwise the request is rejected with `ERR_FAMILY_MISMATCH`); a `kind` of either `MEDICAL` (covering treatments) or `PICKUP` (covering people permitted to retrieve the child); a `scope_text` free-form description of what the authorization covers (1–500 characters); an `effective_at` instant from which the authorization is valid; and an `expires_at` instant strictly greater than `effective_at`. A request where `expires_at` is at or before `effective_at` is rejected with `ERR_INVALID_TIME_RANGE`. New authorizations start in `ACTIVE` state, and the side effect of creation is a re-projection of the child's `medical_authorization_status` or `pickup_authorization_status` per the projection rules in §2.8.

The lifecycle for an authorization is straightforward but has two exits. The system itself transitions an authorization from `ACTIVE` to `EXPIRED` during a clock advance whenever the new logical clock is at or after `expires_at`; this transition recomputes the parent child's derived status fields and, if no remaining `ACTIVE` row of that kind exists for the child, the corresponding child status flips to `EXPIRED`. Either a `Guardian` of the family or a `ProgramAdmin` can also revoke an authorization that is currently `ACTIVE`, moving it to `REVOKED` and recording the current clock as `revoked_at`. Revocation has a substantial downstream effect when the child has any `CONFIRMED` enrollment in a future or current week — i.e., the session-week window `Session.week_start` plus seven days times the enrollment's `week_index` is strictly after the current clock — and the revocation causes the child's `medical_authorization_status` or `pickup_authorization_status` to drop below `ACTIVE`. In that case, each such enrollment is moved from `CONFIRMED` to `CANCELLED` (cascade), `cancelled_at` is set to the current clock, and the standard confirmed-cancellation side-effect chain runs for each one: the scholarship credit is refunded against the originally consumed award, the sibling discount is recomputed on every remaining `CONFIRMED` sibling in the same `(session_id, week_index)`, and the lowest-positioned `WAITLISTED` enrollment in that week is promoted if one exists. Revoking an authorization that is not `ACTIVE` (already `EXPIRED` or already `REVOKED`) is rejected with `ERR_INVALID_STATE`.

If a `Guardian` revokes a medical authorization while a parallel request tries to confirm a `PENDING_AUTH` enrollment for the same child, exactly one operation succeeds; the operations serialize first-writer-wins on `Child.medical_authorization_status`, and the loser sees `ERR_AUTHORIZATION_NOT_ACTIVE` (HTTP 409) for the broken invariant.

### 3.3. Sessions and Their Lifecycle

A `ProgramAdmin` creates a session in `DRAFT` state. The intake payload supplies a `title` (1–120 characters), a `kind` of either `AFTERSCHOOL` or `SUMMER_CAMP`, an inclusive age window via `age_min` and `age_max` where both values lie between 3 and 17 and `age_min` is at most `age_max`, a `reference_date` (the ISO calendar date against which each child's age in whole years is computed at enrollment evaluation), a `weekly_capacity` between 1 and 200 setting the per-week seat ceiling, a `week_start` (an ISO date that must fall on a Monday — the first enrollable ISO week), a `week_count` between 1 and 12 giving the number of consecutive enrollable weeks, a `base_weekly_fee_cents` non-negative integer giving the per-week list price before any discount, and a `rainy_day_pool_per_week` of indoor backup seats reserved for weather reroutes that must lie between 0 and `weekly_capacity` inclusive. The new session starts at `status` `DRAFT`.

A `DRAFT` session does not yet accept enrollment confirmations. The admin opens it via a session-open action that transitions `DRAFT → OPEN`. Three preconditions guard this transition: `week_count` must be at least 1, `weekly_capacity` must be at least 1, and `age_min` must be at most `age_max`. Any violation yields `ERR_INVALID_STATE`. The transition has a substantive side effect: the system materializes one `SessionDay` row for every business day inside each ISO week of the session — the granular calendar against which weather posture is then set. Each generated `SessionDay` carries its parent `session_id`, the `week_index` it belongs to (0-based), a `day_date` ISO date, a starting `weather_status` of `NORMAL`, and computed counters `rainy_day_used` and `outdoor_headcount` both at 0. The session's `status` is set to `OPEN`.

A `ProgramAdmin` can also cancel a session. From `DRAFT`, cancellation has no preconditions and simply sets `status` to `CANCELLED`. From `OPEN`, cancellation requires that the session currently be `OPEN` and cascades: every `Enrollment` on this session in a non-terminal state (`PENDING_AUTH`, `CONFIRMED`, or `WAITLISTED`) is moved to `CANCELLED`. For each cancelled enrollment that had been `CONFIRMED`, the system additionally recomputes `ScholarshipAward.consumed_credit_cents` for the award that the enrollment had consumed, and triggers a sibling-discount recomputation on every remaining `CONFIRMED` sibling enrollment in the same `(session_id, week_index)`. Cancellation from any state other than `DRAFT` or `OPEN` is rejected as `ERR_INVALID_STATE`.

End-of-program close moves an `OPEN` session to `CLOSED`. The single precondition is that every week of the session has reached `week_start` plus seven calendar days on the logical clock — i.e., every enrollable week has fully elapsed. As side effects, every `Enrollment` on the session that is currently `CONFIRMED` is auto-transitioned to `COMPLETED`, and every `Enrollment` that is `PENDING_AUTH` or `WAITLISTED` is auto-transitioned to `CANCELLED` with `cancelled_at` set to the current clock. Both `CLOSED` and `CANCELLED` are terminal for a session — no further state change is permitted, and any attempt yields `ERR_INVALID_STATE`.

### 3.4. The Enrollment Pipeline

A guardian or admin creates an `Enrollment` for a specific `(child_id, session_id, week_index)` tuple. The new row starts at `PENDING_AUTH` and the system runs a precheck on this triple: the `week_index` must be at least 0 and strictly less than the session's `week_count`, otherwise the request fails with `ERR_INVALID_WEEK_INDEX`; the child's age in whole years on the session's `reference_date` must be in the inclusive interval from `age_min` to `age_max`, otherwise the request fails with `ERR_AGE_OUT_OF_RANGE` and no row is created. The age computation itself takes the integer floor of the calendar-day difference between `Session.reference_date` and `Child.date_of_birth` divided by 365.2425 days; the result is compared inclusively against the window. Duplicates are forbidden: any non-terminal `Enrollment` already existing for the same `(child_id, session_id, week_index)` causes the new attempt to fail with `ERR_DUPLICATE_ENROLLMENT`.

A `PENDING_AUTH` enrollment is converted to `CONFIRMED` by an explicit confirmation action by a `Guardian` of the same family or by a `ProgramAdmin`. The confirmation has a tight gate. First, the parent `Session` must currently be `OPEN`; otherwise the transition is rejected with `ERR_INVALID_STATE`. Then the safety triad is evaluated in order: the child's `medical_authorization_status` must be `ACTIVE` at request time (else `ERR_MEDICAL_AUTH_REQUIRED`), the child's `pickup_authorization_status` must be `ACTIVE` at request time (else `ERR_PICKUP_AUTH_REQUIRED`), and the child's `emergency_contact_count` must be at least 1 (else `ERR_EMERGENCY_CONTACT_REQUIRED`). Then the age check is re-run against the same `reference_date` snapshot that was taken at creation — even if the child has aged out between creation and confirmation, the snapshot taken at creation is what governs (this is the chronological reading; re-evaluation against a fresh date is explicitly the wrong algorithm). Finally, the per-week capacity precondition is consulted.

The capacity gate has two outcomes. If the count of currently-`CONFIRMED` enrollments for the target `(session_id, week_index)` is strictly less than `Session.weekly_capacity`, the enrollment proceeds to `CONFIRMED` and the snapshot side-effects in §3.5 run. If the count is exactly at capacity, the enrollment instead transitions `PENDING_AUTH → WAITLISTED`, and its `waitlist_position` is set to one plus the maximum of existing `waitlist_position` values for the same `(session_id, week_index)`. There is no error in the waitlist path — this is normal behavior. Only the race condition where two callers attempt to grab the same final seat at the same time produces `ERR_WEEKLY_CAPACITY_FULL` (HTTP 409), and only for the loser of the serialization.

A guardian or admin may also cancel an enrollment. Cancelling a `PENDING_AUTH` row simply records `cancelled_at` and ends the lifecycle. Cancelling a `WAITLISTED` row records `cancelled_at` and additionally renumbers the remaining `WAITLISTED` rows in the same `(session_id, week_index)` so that `waitlist_position` is contiguous starting at 1. Cancelling a `CONFIRMED` row requires the parent session to be `OPEN` (cancellation after `CLOSED` is rejected with `ERR_INVALID_STATE`) and triggers the full unwind: `cancelled_at` is recorded, the snapshotted `scholarship_discount_cents` is refunded back to the consumed `ScholarshipAward` (its `consumed_credit_cents` is decreased by exactly that amount, and if that award had reached `EXHAUSTED` and now has remaining credit, it transitions back to `ACTIVE`), every remaining `CONFIRMED` sibling enrollment of the same family in the same `(session_id, week_index)` has its `sibling_discount_cents` recomputed and `final_fee_cents` updated, and the lowest-positioned `WAITLISTED` enrollment in that week — if any — is promoted via a system transition that re-runs all of the confirmation preconditions (active medical, active pickup, sufficient emergency contacts) and the full snapshot chain. If the candidate promotion fails the re-check because, for example, its authorizations have since expired, that candidate is skipped and the next `WAITLISTED` entry is attempted, until one passes or the queue is exhausted.

The terminal `COMPLETED` and `CANCELLED` enrollment states are reached either directly (cancellation by request) or as cascaded side-effects of the session lifecycle: a session moving to `CLOSED` auto-completes its still-`CONFIRMED` enrollments and auto-cancels everything else non-terminal; a session moving to `CANCELLED` cancels everything non-terminal. In both of these system-driven cancellations, `cancelled_at` is set, but the scholarship refund and sibling recompute only fire on cancellations that came from a previously `CONFIRMED` state (since `PENDING_AUTH` and `WAITLISTED` enrollments had no snapshot to unwind).

### 3.5. Fee Snapshotting at Confirmation

When an enrollment becomes `CONFIRMED` — whether from the `PENDING_AUTH → CONFIRMED` happy path or via system promotion from `WAITLISTED → CONFIRMED` — the system computes and snapshots the financial figures onto the row. The computation runs in a fixed order. First, `list_fee_cents` is set to the parent session's `base_weekly_fee_cents`. Second, the sibling discount is computed and snapshotted into `sibling_discount_cents`. Third, the scholarship allocation is computed and snapshotted into `scholarship_discount_cents`, with `scholarship_award_id` set to the consumed award (or left null when no award applied). Fourth, `final_fee_cents` is set to the larger of zero and `list_fee_cents` minus `sibling_discount_cents` minus `scholarship_discount_cents` — in plain prose, the list fee with both discounts subtracted, never below zero. The chosen `ScholarshipAward` then has its `consumed_credit_cents` increased by the snapshotted scholarship discount; if that increase brings `consumed_credit_cents` exactly equal to the award's `total_credit_cents`, the award is auto-transitioned to `EXHAUSTED`.

The sibling-discount rule uses tiered pricing on the count of currently-`CONFIRMED` enrollments belonging to children of the same family in the same `(session_id, week_index)`, including the about-to-be-confirmed row itself. Let that count be N. When N equals 1, no sibling discount applies (the percentage is zero). When N equals 2, the per-row percentage is 10 percent. When N equals 3, the per-row percentage is 15 percent. When N is 4 or more, the per-row percentage is 20 percent. The dollar discount for each affected enrollment is `list_fee_cents` multiplied by the per-row percentage, then rounded half-up to whole cents independently for each line item before the family-level summation. The order is pinned: determine N first, then derive each affected enrollment's percentage from the tier table, then multiply, then round per-line. Summing first and then rounding is explicitly forbidden, since on percentage tiers it can produce a different family total by one cent. After the about-to-be-confirmed row's own `sibling_discount_cents` is computed, every other already-`CONFIRMED` sibling enrollment in the same `(session_id, week_index)` has its `sibling_discount_cents` recomputed under the new N and its `final_fee_cents` updated accordingly (this is the cascade).

The scholarship allocation is a waterfall over the family's existing `ScholarshipAward` rows. The system first filters to awards that are currently `ACTIVE` and whose `granted_for_kind` matches the parent session's `kind` exactly or is `ANY`. The eligible list is then ordered: awards whose `granted_for_kind` matches the session's `kind` exactly come ahead of awards granted with `ANY` (specific before generic); within each group, awards with larger remaining credit (`total_credit_cents` minus `consumed_credit_cents`) come first; and the final tiebreak is the earlier `created_at`. The algorithm then iterates this ordered list and allocates from the first award whose remaining credit is at least 1 cent. The amount allocated is the smaller of that award's remaining credit and the net payable amount, where the net payable amount is `list_fee_cents` minus the already-computed `sibling_discount_cents`. Only one award may be applied per enrollment — there is no chaining across multiple awards on the same row. If no eligible award exists, or if the net payable amount is already zero, then `scholarship_discount_cents` is zero and `scholarship_award_id` remains null. Awards that are not `ACTIVE` (i.e., `EXHAUSTED` or `REVOKED`), or whose `granted_for_kind` is incompatible with the session's `kind`, are skipped silently when they would otherwise be considered; if the caller explicitly names an ineligible award (e.g., revoked), the confirmation is rejected with `ERR_SCHOLARSHIP_INELIGIBLE`.

Two confirmations racing to consume the last cent of a `ScholarshipAward`'s remaining credit serialize first-writer-wins on the award's `consumed_credit_cents`. The total `consumed_credit_cents` is not permitted to exceed `total_credit_cents` under any race; the second confirmation that would overflow is rejected with `ERR_SCHOLARSHIP_EXHAUSTED` (HTTP 409).

The provisional fee-quote capability returns a what-if computation using the *current* (pre-confirmation) sibling count for the requested `(session_id, week_index)` and the *current* award balances. The quote returns the same shape of figures — `list_fee_cents`, `sibling_discount_cents`, `scholarship_discount_cents`, `final_fee_cents`, and `scholarship_award_id` of the award the allocation would currently choose — but it explicitly does not snapshot anything onto the enrollment row, and the values returned at quote time may legitimately differ from what is later snapshotted at confirmation if balances or sibling counts have moved in the interim.

### 3.6. Scholarship Awards

A scholarship award is granted to a family by a `ProgramAdmin`. The award carries `total_credit_cents` (at least 1) and `granted_for_kind` selecting which session kind it may be applied against: `AFTERSCHOOL` only, `SUMMER_CAMP` only, or `ANY` (both). The award starts at `ACTIVE` with `consumed_credit_cents` zero. Consumption is tracked on the award as `consumed_credit_cents` and is updated only via the confirmation and cancellation side-effect chains described in §3.5 and §3.4 — there is no direct mutation endpoint. When `consumed_credit_cents` reaches `total_credit_cents` exactly, the award auto-transitions to `EXHAUSTED`. If a subsequent confirmed-enrollment cancellation refunds credit back below `total_credit_cents`, an `EXHAUSTED` award auto-transitions back to `ACTIVE`.

An admin can also revoke an award, moving `ACTIVE` or `EXHAUSTED` to `REVOKED` and recording `revoked_at`. Revocation is deliberately a soft termination on the award itself: enrollments that are already `CONFIRMED` and were charged against this award keep their snapshotted `scholarship_discount_cents` unchanged — snapshots are immutable post-confirmation. What revocation does prevent is any future confirmation attempt that names this award (explicitly or via the waterfall), which is then rejected at confirmation with `ERR_SCHOLARSHIP_INELIGIBLE` rather than silently skipping. Attempting to revoke an already-`REVOKED` award is rejected as `ERR_INVALID_STATE`.

### 3.7. Family Invoicing

The family-invoice view answers the question "how much does the household owe for a specific week?" The caller supplies a `week_start` ISO date that identifies an ISO week, and the system iterates every `CONFIRMED` enrollment for any child in this family whose session-week aligns: i.e., `Session.week_start` plus seven days multiplied by the enrollment's `week_index` equals the requested `week_start`. The invoice totals the per-row snapshotted `final_fee_cents` over those rows — the implementation must read the snapshots, not re-derive them from current sibling counts or award balances. The response surfaces `family_id`, `week_start`, the total in `invoice_total_cents`, and the matching `Enrollment` rows as line items. The integer-cent total is already at the correct precision because per-row figures were rounded at confirmation time.

### 3.8. Weather Posture and Rainy-Day Reroute

Once a session is `OPEN`, the system materializes a `SessionDay` row for every business day in every ISO week, and a `ProgramAdmin` can adjust the day's `weather_status` to reflect operational reality. The starting `weather_status` of every materialized day is `NORMAL`. Setting the weather to `RAINY` or `CLOSED` is only permitted when the `day_date` is at or after the current calendar date on the logical clock; attempting to alter a past day's weather is rejected with `ERR_INVALID_WEEK_INDEX`. Setting weather on a `RAINY` or `CLOSED` day requires the parent session to be `OPEN` as well for the `NORMAL → RAINY` direction.

When a day transitions from `NORMAL` to `RAINY`, the system computes a reroute as a side-effect. The count of attendees scheduled to attend that day (`confirmed_attendees_for_day`) is the count of `CONFIRMED` enrollments for the day's parent `(session_id, week_index)`. The week's rainy-day pool budget is `Session.rainy_day_pool_per_week`; the budget already consumed by other days in the same week is the sum of `rainy_day_used` across `SessionDay` rows in the same `(session_id, week_index)` whose `weather_status` is currently `RAINY`, excluding the current day being transitioned. The remaining pool is the larger of zero and the per-week budget minus the already-consumed amount. The `rainy_day_used` value persisted on the current day is set to the smaller of `confirmed_attendees_for_day` and the remaining pool; the day's `outdoor_headcount` is set to `confirmed_attendees_for_day` minus the persisted `rainy_day_used`. The pool is therefore consumed in the order in which days were marked `RAINY`, not in chronological day-date order — if the later day in a week was set `RAINY` first and an earlier day is set `RAINY` afterward, the pool already used by the later day still counts against the earlier day's allocation, because the computation reads currently persisted state at the moment of the transition. The forward-looking alternative of resorting days into chronological order and reallocating from scratch is explicitly the wrong algorithm here.

When a day transitions from `NORMAL` to `CLOSED`, both `outdoor_headcount` and `rainy_day_used` are set to zero on that day. When a `RAINY` day reverts to `NORMAL`, `rainy_day_used` is set to zero and `outdoor_headcount` is set to `confirmed_attendees_for_day`. When a `CLOSED` day reverts to `NORMAL`, the same effect applies: `outdoor_headcount` equals `confirmed_attendees_for_day` and `rainy_day_used` is zero. Transitions `RAINY → CLOSED`, `CLOSED → RAINY`, and any attempt that does not match one of the four legal pairs are rejected with `ERR_INVALID_STATE`.

Two callers racing to set weather on the same day are serialized first-writer-wins on `(session_day_id, weather_status)`. The loser is rejected with `ERR_STALE_VERSION` (HTTP 409); the rule applies even though a `SessionDay` carries no `version` field, because the contention is on the durable persistence of the chosen `weather_status`.

A separate diagnostic capability returns a preview of what would happen if a particular day were marked `RAINY`. The preview returns `confirmed_attendees_for_day`, `pool_already_used_in_week`, `pool_remaining`, `would_reroute` (the count that would be moved indoors), and `outdoor_overflow` (the count that would remain outdoors after the pool is consumed). When the preview indicates that the pool is insufficient to cover the day's attendees, the diagnostic returns `ERR_RAINY_POOL_EXHAUSTED` (HTTP 422). This is informational only — the actual weather-set action does not return this error; pool insufficiency does not block the transition, it merely results in non-zero `outdoor_headcount` and is operator-visible.

## 4. Endpoint Definitions

Endpoints follow conventional HTTP semantics: a successful resource creation returns 201 with the created resource in `data`; a successful modification, read, or transition returns 200; a successful soft-delete returns 204 with an empty body; and any 4xx response carries the standard error envelope from §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /camp/families | Create a family household | ProgramAdmin |
| GET | /camp/families/{id} | Read a family with derived fields | ProgramAdmin, Guardian |
| PATCH | /camp/families/{id} | Update mutable family fields; OCC via version | ProgramAdmin |
| DELETE | /camp/families/{id} | Soft-delete a family; rejects if future confirmed enrollments exist | ProgramAdmin |
| GET | /camp/families/{id}/invoice | Family invoice for a week | ProgramAdmin, Guardian |
| POST | /camp/families/{family_id}/guardians | Add a guardian to a family | ProgramAdmin, Guardian |
| GET | /camp/families/{family_id}/guardians | List guardians for a family (paginated) | ProgramAdmin, Guardian |
| POST | /camp/families/{family_id}/children | Register a child | ProgramAdmin, Guardian |
| GET | /camp/children/{id} | Read a child (derived auth statuses + contact count) | ProgramAdmin, Guardian |
| POST | /camp/children/{child_id}/emergency-contacts | Add an emergency contact | ProgramAdmin, Guardian |
| DELETE | /camp/emergency-contacts/{id} | Archive an emergency contact | ProgramAdmin, Guardian |
| POST | /camp/children/{child_id}/authorizations | Create a parental authorization | ProgramAdmin, Guardian |
| POST | /camp/authorizations/{id}/revoke | Revoke an active authorization | ProgramAdmin, Guardian |
| POST | /camp/sessions | Create a session in DRAFT | ProgramAdmin |
| POST | /camp/sessions/{id}/open | Transition session DRAFT to OPEN | ProgramAdmin |
| POST | /camp/sessions/{id}/close | Transition session OPEN to CLOSED at end-of-program | ProgramAdmin |
| POST | /camp/sessions/{id}/cancel | Cancel a session in DRAFT or OPEN | ProgramAdmin |
| GET | /camp/sessions | List sessions, filterable by kind and status | ProgramAdmin, Guardian |
| GET | /camp/sessions/{id} | Read a session | ProgramAdmin, Guardian |
| POST | /camp/enrollments | Create a PENDING_AUTH enrollment | ProgramAdmin, Guardian |
| POST | /camp/enrollments/{id}/confirm | Confirm a PENDING_AUTH enrollment; may waitlist | ProgramAdmin, Guardian |
| POST | /camp/enrollments/{id}/cancel | Cancel an enrollment; cascades sibling recompute + waitlist promotion | ProgramAdmin, Guardian |
| GET | /camp/enrollments/{id} | Read an enrollment | ProgramAdmin, Guardian |
| GET | /camp/enrollments/{id}/fee-quote | Provisional what-if fee quote | ProgramAdmin, Guardian |
| GET | /camp/sessions/{id}/roster | List enrollments for a session, filterable by week_index and status | ProgramAdmin |
| POST | /camp/families/{family_id}/scholarships | Grant a scholarship to a family | ProgramAdmin |
| POST | /camp/scholarships/{id}/revoke | Revoke a scholarship award | ProgramAdmin |
| GET | /camp/session-days/{id} | Read a session day with weather and headcounts | ProgramAdmin, Guardian |
| POST | /camp/session-days/{id}/set-weather | Set weather posture; triggers rainy-day reroute calc | ProgramAdmin |
| GET | /camp/session-days/{id}/reroute-preview | Diagnostic preview of a hypothetical RAINY day | ProgramAdmin |
| POST | /_clock/advance | Advance the test clock; runs expiry sweep and re-projection | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_FAMILY_MISMATCH | 403 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_TIME_RANGE | 422 |
| ERR_INVALID_WEEK_INDEX | 422 |
| ERR_AGE_OUT_OF_RANGE | 422 |
| ERR_MEDICAL_AUTH_REQUIRED | 422 |
| ERR_PICKUP_AUTH_REQUIRED | 422 |
| ERR_EMERGENCY_CONTACT_REQUIRED | 422 |
| ERR_AUTHORIZATION_NOT_ACTIVE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
| ERR_WEEKLY_CAPACITY_FULL | 409 |
| ERR_SCHOLARSHIP_INELIGIBLE | 422 |
| ERR_SCHOLARSHIP_EXHAUSTED | 409 |
| ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN | 409 |
| ERR_RAINY_POOL_EXHAUSTED | 422 |
| ERR_STALE_VERSION | 409 |
| ERR_FAMILY_HAS_FUTURE_ENROLLMENTS | 409 |
