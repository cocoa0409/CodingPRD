# Newsroom Editorial Workflow API — Product Requirements Document

## 1. Introduction

A metro daily newsroom is a continuous negotiation between ambition and constraint: reporters and photographers pitch more stories than the desk can crew, editors must shepherd each accepted piece through editing, fact-check, and legal review before it can claim a slot in a print, digital, or broadcast window, and a single breaking event can invalidate an entire afternoon's staffing plan. This document specifies the Newsroom Editorial Workflow API, a system that governs that lifecycle end to end — story pitch intake and assignment-desk prioritization, reporter and photographer assignment under workload and time-conflict limits, deadline and slot planning across the three publication channels, staged editorial review with fact-check and legal sign-off, embargo and publication scheduling, corrections policy and issuance, breaking-news overrides with staffing call-ins, and audience performance analytics that feed back into desk prioritization.

The API is built for a newsroom that takes accountability seriously. Editorial authority is segregated so that no one reviews, clears, or approves their own work; the desk acts on pinned, optimistic-concurrency views of stories so a verdict never attaches to content the reviewer did not see; workload and slot-reservation counters are maintained as live compensating invariants rather than recomputed on demand by clients; and all time-dependent behavior — deadline pressure, embargoes, publication windows, call-in expiry, payroll weeks — is evaluated against a deterministic logical clock. All newsroom resources are mounted under the `/newsroom` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes nine roles, spelled exactly as follows: `Reporter`, `Photographer`, `CopyEditor`, `FactChecker`, `LegalReviewer`, `AssignmentEditor`, `ManagingEditor`, `NewsDirector`, and `AnalyticsProducer`. A request whose headers are missing, whose role is not one of these nine values, or — for any entity-backed role — whose `X-User-ID` does not resolve to an existing staff member is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among an endpoint's permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity binds to resources as follows. When `X-User-Role` is `Reporter`, `Photographer`, `CopyEditor`, `FactChecker`, `LegalReviewer`, `AssignmentEditor`, `ManagingEditor`, or `AnalyticsProducer`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a staff member compare the resource's staff foreign-key field to `X-User-ID`. When `X-User-Role` is `NewsDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `declared_by` on a breaking-news event) but does not compare it to any entity's `id`. This opaque identity is what allows the very first staff member to be created from an empty database.

Note that a staff member's API role and their editorial capability are distinct vocabularies. A `StaffMember` carries a `role_capability` drawn from `REPORTER`, `PHOTOGRAPHER`, `COPY_EDITOR`, `FACT_CHECKER`, `LEGAL_REVIEWER`, `DESK_EDITOR`, `MANAGING_EDITOR`, `NEWS_DIRECTOR`, or `ANALYST`, and a `home_desk` drawn from `METRO`, `BUSINESS`, `SPORTS`, or `FEATURES`; these editorial enums govern assignment matching and desk weighting, independent of the CamelCase header roles above.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock (§2.4).
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

A request that matches no defined route, or a defined route under an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404) in this same error envelope.

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, a non-integer value also falls back to the default, and an integer outside the range 1 to 100 is clamped into that range rather than rejected. The `offset` parameter sets how many items to skip and defaults to 0; a non-integer value falls back to 0 and a negative integer is clamped up to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Filter parameters are matched by exact equality and are not themselves validated against enum domains, so a filter value that matches no resource simply yields an empty page.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties broken by creation (request-arrival) order. This ordering is deterministic rather than identifier-ordered; because the logical clock only moves when explicitly set, resources created under an unmoved clock share a `created_at`, and their relative order follows the order in which they were created.

### 2.4. The Logical Newsroom Clock

All temporal evaluation in the system — deadline pressure in priority scoring, embargo checks, publication windows, call-in expiry, completion timestamps, and payroll week boundaries — is driven by a single logical clock, never by the host machine's wall clock. At startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must not fall back to wall-clock time under any circumstance. A `NewsDirector`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and responds with the new `current_utc`; the supplied instant is applied verbatim, with no requirement that it be later than the current value. Whenever this document says "now", it means the logical clock.

### 2.5. Common Resource Properties

Primary resources — staff members, pitches, stories, assignments, publication slots, corrections, breaking-news events, and staffing call-ins — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at 1 and increments by exactly one on every mutation of the resource, including mutations driven by system side effects; it is the basis of optimistic concurrency control.

Two resources are exceptions. A `ReviewRecord` and an `AnalyticsReport` are immutable measurements: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from their representations.

### 2.6. Nested Resource Resolution and Identifier Errors

Requests that target a resource by path are validated left to right. Each parameterized segment — `staffId`, `pitchId`, `storyId`, `assignmentId`, `slotId`, `correctionId`, `eventId`, or `callInId` — must resolve to an existing resource, and the request is rejected with the 404 error matching the first segment that does not resolve: `ERR_STAFF_NOT_FOUND`, `ERR_PITCH_NOT_FOUND`, `ERR_STORY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_CALL_IN_NOT_FOUND` respectively. Foreign keys supplied in request bodies are checked after path resolution: proposing an assignment rejects an unknown `story_id` with `ERR_STORY_NOT_FOUND` and an unknown `staff_id` with `ERR_STAFF_NOT_FOUND`; scheduling rejects an unknown `slot_id` with `ERR_SLOT_NOT_FOUND`; linking a follow-up rejects an unknown `superseding_story_id` with `ERR_STORY_NOT_FOUND`.

### 2.7. Validation Order

Every write request passes through a single ordered validation pipeline, and the first failing check determines the error returned. The order is:

1. Authentication — headers present, role recognized, and the entity-backed user resolved; failures yield `ERR_UNAUTHENTICATED` (HTTP 401).
2. Role authorization — the acting role appears in the endpoint's permitted roles; failures yield `ERR_FORBIDDEN` (HTTP 403).
3. Path-parameter existence, resolved left to right as described in §2.6; failures yield the matching 404.
4. Request-body schema — required fields present, types correct, and enum values inside their declared domains (`urgency`, `story_type`, `severity`, `review_type`, `verdict`, `variant`, `channel`, `role_capability`, `home_desk`, `employment_status`, `assignment_role`); failures yield `ERR_VALIDATION` (HTTP 400).
5. Request-body foreign-key existence, per §2.6; failures yield the matching 404.
6. Ownership scope, where the endpoint declares one — pitch withdrawal compares against the pitch's `submitting_staff_id`, story field edits and submission-for-edit compare against the story's `author_staff_id`, assignment accept, decline, and field-staff completion compare against the assignment's `staff_id`, and call-in confirm or decline compares against the call-in's `staff_id`; failures yield `ERR_FORBIDDEN` (HTTP 403).
7. Optimistic concurrency on the two OCC-guarded writes (§2.8); a stale token yields `ERR_STALE_VERSION` (HTTP 412). This check runs before the from-state check, so a stale token produces 412 even when the target's state is also wrong.
8. From-state legality — the target resource is in a from-state of the invoked transition; failures yield `ERR_INVALID_STATE` (HTTP 409), except that proposing a correction or ingesting analytics against a story that is not published yields `ERR_STORY_NOT_PUBLISHED` (HTTP 409).
9. Segregation of duties (§2.9); failures yield `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).
10. The editorial staffing gate on submission for edit; failures yield `ERR_NO_REPORTING_ASSIGNMENT` (HTTP 422).
11. Referential usability — the referenced staff member's `employment_status` is `ACTIVE` at assignment proposal and acceptance (`ERR_STAFF_INACTIVE`, HTTP 422), the proposed `assignment_role` equals the staff member's `role_capability` (`ERR_CAPABILITY_MISMATCH`, HTTP 422), and at scheduling the story's `story_type` equals the slot's `channel` (`ERR_CHANNEL_MISMATCH`, HTTP 422).
12. Temporal sanity — interval ordering on assignments, slots, events, and analytics windows (`ERR_INVALID_INTERVAL`, HTTP 422), the embargo-versus-slot check at scheduling (`ERR_EMBARGO_BEYOND_SLOT`, HTTP 422), and call-in expiry at confirm or decline (`ERR_CALL_IN_EXPIRED`, HTTP 409).
13. Mutual exclusion and uniqueness — staff time overlap (`ERR_STAFF_TIME_CONFLICT`, HTTP 409), same-channel slot window spacing (`ERR_SLOT_WINDOW_CONFLICT`, HTTP 409), analytics window uniqueness (`ERR_DUPLICATE_ANALYTICS_WINDOW`, HTTP 409), slot cancellation with reservations outstanding (`ERR_SLOT_NOT_EMPTY`, HTTP 409), and the pitch rework limit (`ERR_PITCH_REWORK_LIMIT`, HTTP 422).
14. Capacity — the assignment acceptance cap (`ERR_ASSIGNMENT_CAP_REACHED`, HTTP 422) and the slot reservation capacity (`ERR_SLOT_CAPACITY_EXCEEDED`, HTTP 422).

### 2.8. Optimistic Concurrency on Story Versions

Exactly two writes are guarded by optimistic concurrency control: scheduling a story into a publication slot, and filing a review verdict on a story. Both require a non-optional `expected_story_version` field carrying the story `version` the caller last observed.

A schedule request whose `expected_story_version` no longer equals the story's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — for example because the story was edited, or re-scheduled by another desk action, since the token was read; the schedule supersedes the desk's prior view of the story. A review verdict pins the exact story version it reviewed: if the story's `version` has advanced since the reviewer's reading — for instance because the author filed a new edit — the verdict is rejected with `ERR_STALE_VERSION` (HTTP 412), so reviews never attach to content the reviewer did not see. Endpoints other than these two do not take a version field. Author field edits on a story increment its `version` without changing its status, which is precisely how outstanding schedule and review tokens go stale.

### 2.9. Segregation of Editorial Duties

Three hand-offs forbid self-dealing, each enforced with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The copy editor who completes an edit and advances a story toward fact-check must not be the story's author. The reviewer filing a fact-check or legal verdict must not be the story's author. And the managing editor who approves a correction must not be the staff member who proposed it. In each case the comparison is between `X-User-ID` and the relevant authorship or proposal field on the resource.

### 2.10. Precision, Rounding, and the Payroll Week

Two precision regimes apply throughout. Scores — priority scores and performance scores — are decimal values rounded half-up to exactly two decimal places, and rounding is applied at each pinned stage of a calculation rather than only at the end. Money is integer cents: provisional and final assignment costs and weekly payroll totals are rounded half-up to zero decimal places.

The payroll week is a half-open interval from Monday 00:00:00 UTC to the following Monday 00:00:00 UTC. Weekly cost allocation processes a staff member's completed assignments in chronological order — by `completed_at` ascending, ties broken by `created_at` ascending — and weekly overtime applies to actual effort beyond the first 2,400 minutes (forty hours) allocated in that order. When a weekly payroll figure is reported, each assignment's cost is rounded to whole cents first and the rounded figures are then summed; minutes are never summed first and rounded once.

### 2.11. Live Counters: Workload, Reservations, and Corrections

Three counters are maintained as compensating invariants, recomputed on every relevant mutation rather than accumulated blindly. A staff member's `active_assignment_count` is the number of their assignments in `PROPOSED` or `ACCEPTED` status — declined, cancelled, completed, and bumped assignments do not count — and it is recomputed on every assignment status mutation affecting that staff member. A publication slot's `reserved_count` is the number of stories pointing at that slot with status `SCHEDULED`; it rises when a story is scheduled into the slot and falls when such a story is unscheduled, killed, or bumped out of the slot. A story's `correction_count` is the number of its corrections that have reached `ISSUED`. The `active_assignment_count` and `reserved_count` recomputes update the counter field in place only: they do not refresh the owning staff member's or slot's `updated_at`, and they do not increment its `version`. A story's `correction_count`, by contrast, rises inside the issuance act of §3.6 and therefore shares that act's `updated_at` refresh and `version` increment.

## 3. Business Logic & Workflows

### 3.1. The Staff Roster and Workload Accounting

Before any story can move, the newsroom needs a roster. A `NewsDirector` onboards a staff member by supplying their `full_name`, editorial `role_capability`, `home_desk`, and `hourly_rate_cents` — a non-negative integer cost rate in cents per hour that feeds both provisional assignment costing and weekly payroll. An optional `max_concurrent_assignments` caps how many accepted assignments the person may hold at once; it defaults to 3 when omitted and must be at least 1. New staff start with `employment_status` set to `ACTIVE` and an `active_assignment_count` of zero.

The roster is queryable by the desk roles (`AssignmentEditor`, `ManagingEditor`, `NewsDirector`) with pagination plus `role_capability`, `employment_status`, and `home_desk` filters, and any of the nine roles may read a single staff member. A `NewsDirector` may later patch a staff member's `employment_status` (to `ON_LEAVE` or `INACTIVE`, or back to `ACTIVE`), `max_concurrent_assignments`, or `hourly_rate_cents`; fields omitted from the request body — or supplied as explicit `null` — are left unchanged, and each patch increments the staff member's `version`. Only staff whose `employment_status` is `ACTIVE` may be proposed for or accept new work, so leave and separation immediately close the staffing pipeline without touching history.

From the roster, the desk can reach a staff member's assignments (pageable, filterable by assignment `status`), the review verdicts they have filed, and — for `ManagingEditor` and `NewsDirector` — the corrections they have proposed or approved and a weekly payroll snapshot. Call-in history for a staff member is visible to the `NewsDirector` alone. The payroll snapshot takes an optional `week_start` query parameter naming the Monday that opens the week, as an ISO date; when omitted it defaults to the week containing the logical clock, and a value that does not name a Monday is rejected as a validation error. The response reports `week_start` (rendered as an ISO calendar date, `YYYY-MM-DD`), the `assignment_count` of completed assignments in that week, the `regular_minutes` and `overtime_minutes` allocated chronologically across them, and the `total_cents` payable.

### 3.2. Pitch Intake and the Desk Review Cycle

Stories enter the newsroom as pitches. Any of the seven desk-side roles — `Reporter`, `Photographer`, `CopyEditor`, `FactChecker`, `LegalReviewer`, `AssignmentEditor`, `ManagingEditor` — may submit one, providing a `title`, a `summary` describing the angle, the target `desk`, and the editorial `deadline_at`; an optional `urgency` of `STANDARD`, `URGENT`, or `BREAKING` defaults to `STANDARD`. The server records the submitter in `submitting_staff_id` from `X-User-ID`, and the pitch lands in `SUBMITTED` status with `rework_round` at 0. The pitch list supports pagination and filtering by `status`, `desk`, `submitting_staff_id`, and `greenlit_story_id`.

An `AssignmentEditor` works the queue. Starting review moves a pitch from `SUBMITTED` to `DESK_REVIEW` and bumps its `version`. From `DESK_REVIEW` the editor has three exits. Returning the pitch sends it back to `SUBMITTED` for rework and increments `rework_round`; the desk will not return a pitch forever — once `rework_round` has reached 3, a further return is rejected with `ERR_PITCH_REWORK_LIMIT` (HTTP 422). Rejecting moves the pitch to `REJECTED`. Greenlighting is the generative exit: the editor supplies a `story_type` of `PRINT`, `DIGITAL`, or `BROADCAST`, the pitch moves to `GREENLIT`, and the system spawns a new story in `DRAFT` status whose `pitch_id` points back to the pitch, whose `desk` is copied from the pitch, whose `author_staff_id` is the pitch's submitter, and whose `word_count` is 0, `embargo_until` and `slot_id` null, and `correction_count` 0. The pitch's `greenlit_story_id` is set to the new story — the reverse lookup of stories spawned from a pitch therefore returns at most one element — and the pitch's `version` increments; the greenlight response is `200 OK` carrying the updated pitch (the spawned story is read back through `greenlit_story_id`). Every transition out of a state the pitch is not in is rejected with `ERR_INVALID_STATE` (HTTP 409).

The submitter retains one right throughout triage: withdrawal. From either `SUBMITTED` or `DESK_REVIEW`, the pitch's owner may withdraw it to `WITHDRAWN`; the attempt is rejected with `ERR_FORBIDDEN` unless `X-User-ID` equals the pitch's `submitting_staff_id`, and with `ERR_INVALID_STATE` once the pitch has reached any other state.

Greenlighting also fixes the story's `priority_score`, the desk's forward-looking ranking figure, computed from the source pitch and the logical clock. The urgency weight is 10 for a `STANDARD` pitch, 25 for an `URGENT` pitch, and 40 for a `BREAKING` pitch, and this weight is doubled. The desk weight — 5 for `METRO`, 4 for `BUSINESS`, 3 for `SPORTS`, 2 for `FEATURES` — is added as-is. Time pressure contributes up to 30 points: measure the hours from now until the pitch's `deadline_at`, subtract that figure from 72, divide the difference by 72, and clamp the fraction so it is never below 0 (a deadline more than 72 hours out contributes nothing) and never above 1 (a deadline at or past the present moment contributes the maximum); multiply the clamped fraction by 30. The base score is the doubled urgency weight plus the desk weight plus the time-pressure points, rounded half-up to two decimal places. This pure desk-forward value — it ignores the author's history entirely — is what is stored on `priority_score`, and it is the figure the breaking-news bump check later compares against the bump floor.

A computed read of a story's priority score remains available to `AssignmentEditor`, `ManagingEditor`, and `NewsDirector`. Its optional `variant` query parameter selects `DESK` (the default) or `ANALYTICS`; any other value is rejected with `ERR_VALIDATION` (HTTP 400). The response carries the echoed `variant` and the computed `score`. Both selections recompute the desk-forward base from the source pitch against the current logical clock at read time: the `DESK` selection returns that recomputed base (equal to the stored `priority_score` only while the clock has not advanced since greenlight), and the `ANALYTICS` selection mixes the recomputed base with the author's track record as described in §3.7, so the same story can score differently once its author has settled analytics.

### 3.3. Crewing the Story: Assignments from Proposal to Payroll

A story in `DRAFT`, `IN_EDIT`, or `ON_HOLD` may be crewed; proposing an assignment against a story in any other state is rejected with `ERR_INVALID_STATE`. The `AssignmentEditor` proposes by naming the `story_id`, the `staff_id`, an `assignment_role` of `REPORTER` or `PHOTOGRAPHER`, a work window from `start_at` to `end_at`, and the `planned_effort_minutes` (at least 1). The referenced story and staff member must exist (`ERR_STORY_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`), the staff member's `employment_status` must be `ACTIVE` (`ERR_STAFF_INACTIVE`, HTTP 422), and the proposed `assignment_role` must equal the staff member's `role_capability` — a photographer cannot be crewed as a reporter (`ERR_CAPABILITY_MISMATCH`, HTTP 422). The window must be sane: `end_at` must fall strictly after `start_at`, otherwise `ERR_INVALID_INTERVAL` (HTTP 422).

The desk's conflict rule treats each assignment window as a half-open interval. A proposal conflicts with any other assignment of the same staff member in `PROPOSED` or `ACCEPTED` status when the new `start_at` falls before the other's `end_at` and the new `end_at` falls after the other's `start_at`; windows that merely touch end-to-start do not conflict. A conflicting proposal is rejected with `ERR_STAFF_TIME_CONFLICT` (HTTP 409). A clean proposal lands in `PROPOSED` status with its `provisional_cost_cents` computed immediately: the planned minutes multiplied by the staff member's per-minute rate (`hourly_rate_cents` divided by 60), rounded half-up to a whole cent, ignoring overtime and actuals entirely. The staff member's `active_assignment_count` is recomputed — the new proposal raises it by one.

Field staff answer their own proposals. Accepting or declining is restricted to `Reporter` and `Photographer` roles acting on their own assignments — the ownership check compares `X-User-ID` to the assignment's `staff_id` and rejects others with `ERR_FORBIDDEN` — and only a `PROPOSED` assignment can be answered (`ERR_INVALID_STATE` otherwise). Acceptance re-verifies the world at the moment of answer: the staff member must still be `ACTIVE` (`ERR_STAFF_INACTIVE`), the half-open overlap check runs again against their other `PROPOSED` and `ACCEPTED` assignments (`ERR_STAFF_TIME_CONFLICT`), and the acceptance cap applies — the staff member's count of `ACCEPTED` assignments must be below their `max_concurrent_assignments`, with rejection exactly when the count already equals the cap (`ERR_ASSIGNMENT_CAP_REACHED`, HTTP 422). Because `PROPOSED` and `ACCEPTED` both count toward `active_assignment_count`, acceptance leaves that counter's value unchanged. Declining moves the assignment to `DECLINED` and recomputes the counter down by one.

One bubble-up exception links acceptance back to the story pipeline: when a story is sitting in `ON_HOLD` because its reporting crew was stripped by a breaking-news bump, and the accepted assignment is a `REPORTER` assignment on that story, the story resumes from `ON_HOLD` to `DRAFT` and its `version` increments.

Completion records reality. The assigned field staff member — or an `AssignmentEditor` on their behalf — completes an `ACCEPTED` assignment by supplying `actual_effort_minutes` (at least 1); the server stamps `completed_at` with the logical clock, recomputes the staff member's `active_assignment_count` down by one, and settles cost. The final cost accounts for weekly overtime: consider every `COMPLETED` assignment of that staff member whose `completed_at` falls inside the same payroll week, process them in chronological order by `completed_at` with ties broken by `created_at` ascending, and keep a running total of actual minutes already allocated. Each assignment's actual minutes split into a regular portion — the smaller of its own actual minutes and the room remaining below the weekly regular threshold of 2,400 minutes (forty hours), never below zero — and an overtime portion of whatever actual minutes remain. The assignment's `final_cost_cents` is the sum of its regular minutes plus its overtime minutes multiplied by 1.5, all multiplied by the per-minute rate, rounded half-up to a whole cent. Completion therefore re-runs this allocation for the staff member's entire payroll week, and an assignment completed earlier in the week can see its `final_cost_cents` change retroactively as later completions push the running total past the threshold. `final_cost_cents` stays null until the assignment completes, and only `COMPLETED` assignments ever enter payroll — proposed, accepted, declined, cancelled, and bumped work is excluded from the weekly snapshot described in §3.1.

The desk may also cancel an assignment in `PROPOSED` or `ACCEPTED` status, moving it to `CANCELLED` and recomputing the staff counter down by one; the same cancellation arrives as a side effect when a story is killed (§3.5). Assignments carry a `bumped_by_event_id` that stays null unless a breaking-news activation bumps the assignment (§3.8).

### 3.4. The Editorial Pipeline: Edit, Fact-Check, and Legal Review

A greenlit story begins in `DRAFT`. Its author — and only its author, enforced by comparing `X-User-ID` to the story's `author_staff_id` with `ERR_FORBIDDEN` on mismatch — may edit the story's `word_count` (a non-negative integer) and `embargo_until` (a nullable embargo instant before which the story may not publish) while the story is in `DRAFT` or `IN_EDIT`; fields omitted from the request body are left unchanged (an explicit `null` `word_count` is treated as omitted), an explicit `null` `embargo_until` clears the embargo, and any such edit call that passes validation increments the story's `version` without changing its status — even when it changes no field value — and it is exactly this version bump that invalidates outstanding schedule and review tokens (§2.8). Attempting the same edit in any later state is rejected with `ERR_INVALID_STATE`.

When the draft is ready, the author submits it for edit, moving the story from `DRAFT` to `IN_EDIT`. The newsroom refuses to edit uncrewed copy: submission requires at least one assignment on the story with `assignment_role` `REPORTER` in `ACCEPTED` or `COMPLETED` status, and without one the request is rejected with `ERR_NO_REPORTING_ASSIGNMENT` (HTTP 422).

From `IN_EDIT`, a `CopyEditor` completes the edit and advances the story to `FACT_CHECK` — provided the copy editor is not the story's author, per §2.9. Review then proceeds as a two-stage gate driven by filed verdicts. A `FactChecker` files a verdict with `review_type` `FACT_CHECK` while the story is in `FACT_CHECK`; a `LegalReviewer` files one with `review_type` `LEGAL` while the story is in `LEGAL_REVIEW`. Each reviewer role may file only its own review type: a `FactChecker` filing `LEGAL`, or a `LegalReviewer` filing `FACT_CHECK`, is rejected with `ERR_FORBIDDEN` (HTTP 403) — a check evaluated immediately after body-schema validation and before the optimistic-concurrency check of §2.8. A filing whose `review_type` does not match the story's current stage, or that arrives in any other state, is rejected with `ERR_INVALID_STATE`; a filing by the story's author is rejected per §2.9; and every filing must pin the story version under review via `expected_story_version` as §2.8 describes, with a stale pin rejected by `ERR_STALE_VERSION` (HTTP 412). Reviewers may attach optional `notes`. Each accepted filing creates a `ReviewRecord` — a 201-created, immutable measurement whose `story_id` comes from the path and whose `reviewer_staff_id` comes from `X-User-ID`, which pins the supplied version in `reviewed_story_version`, whose `review_round` is the count of prior reviews of the same type for the story plus one, and whose `is_current` flag is true only on the latest review of its type for the story: recording a newer review of that type flips every earlier same-type review of the story to `is_current` false.

The verdict drives the pipeline symmetrically in both stages. A `PASS` in `FACT_CHECK` advances the story `FACT_CHECK → LEGAL_REVIEW`; a `PASS` in `LEGAL_REVIEW` advances it `LEGAL_REVIEW → CLEARED`. A `FAIL` in either stage loops the story back to `IN_EDIT` for revision, and the round counter ensures each pass through the loop is recorded as a new round rather than overwriting history. Every accepted filing also increments the story's `version` alongside the transition. A `ManagingEditor` retains one override: reopening a `CLEARED` story sends it back to `IN_EDIT` as a major revision — the prior review records remain, but the pipeline must be re-run before the story can be cleared again. Stories support list filtering by `status`, `desk`, `author_staff_id`, and `superseded_by_story_id`; a story's assignments, its review records (filterable by `review_type`), its corrections (filterable by `status`), and its analytics reports (filterable by `variant`) are each readable as reverse collections, with the review and assignment collections restricted to the desk and review roles.

### 3.5. Publication Slots, Scheduling, and Going to Press

Cleared stories compete for publication capacity. An `AssignmentEditor` or `ManagingEditor` opens a publication slot by declaring its `channel` (`PRINT`, `DIGITAL`, or `BROADCAST`), a `window_start` and `window_end`, and a `capacity` of at least 1. The window must be sane — `window_end` strictly after `window_start`, else `ERR_INVALID_INTERVAL` — and slots on the same channel must respect turnaround: a new slot conflicts with an existing `ACTIVE` slot on the same channel unless their windows are separated by strictly more than 30 minutes, so an exact 30-minute gap still conflicts, as does any overlap or smaller gap, and the violation is rejected with `ERR_SLOT_WINDOW_CONFLICT` (HTTP 409). A new slot opens `ACTIVE` with `reserved_count` 0. Slots are listable by anyone with `channel` and `status` filters, and the stories scheduled into a slot are readable as a reverse collection by the desk roles.

Scheduling is the desk's commitment move. An `AssignmentEditor` schedules a `CLEARED` story into a slot by naming the `slot_id` and pinning the story version per §2.8; a stale `expected_story_version` is rejected with `ERR_STALE_VERSION`. The slot must exist (`ERR_SLOT_NOT_FOUND`) and still be `ACTIVE` (`ERR_INVALID_STATE`). Three fit checks then apply: the story's `story_type` must equal the slot's `channel` — print copy does not go into a broadcast window (`ERR_CHANNEL_MISMATCH`, HTTP 422); the story's `embargo_until`, when set, must fall no later than the slot's `window_end` (`ERR_EMBARGO_BEYOND_SLOT`, HTTP 422); and the slot must have room — `reserved_count` below `capacity`, with rejection exactly when the count already equals capacity (`ERR_SLOT_CAPACITY_EXCEEDED`, HTTP 422). A successful schedule moves the story `CLEARED → SCHEDULED`, sets its `slot_id`, raises the slot's `reserved_count` by one, and increments the story's `version`. Unscheduling reverses the move — `SCHEDULED → CLEARED`, the slot's `reserved_count` drops by one, and `slot_id` returns to null.

Publication itself is a system act, not a per-story call. A `NewsDirector` triggers an operations checkpoint that publishes every `SCHEDULED` story whose slot's `window_start` has been reached by the logical clock and whose embargo is satisfied — `embargo_until` null or no later than now. Each published story moves `SCHEDULED → PUBLISHED`, records `published_at` as now, and increments its `version`; publication leaves the story's `slot_id` in place and does not recompute the slot's `reserved_count`, so a slot's scheduled-stories collection also lists stories already published from it. The same checkpoint also sweeps staffing call-ins (§3.8), and its response lists the `published_story_ids` and `expired_call_in_ids` it processed (each in creation order).

Two editorial controls remain before and after the presses. A `ManagingEditor` may kill a story from any pre-publication state — `DRAFT`, `IN_EDIT`, `FACT_CHECK`, `LEGAL_REVIEW`, `CLEARED`, `SCHEDULED`, or `ON_HOLD` — moving it to `KILLED`; attempting to kill a `PUBLISHED` or `RETRACTED` story is rejected with `ERR_INVALID_STATE`. The kill cascades: every assignment on the story still in `PROPOSED` or `ACCEPTED` moves to `CANCELLED` with each affected staff member's `active_assignment_count` recomputed, and if the story was `SCHEDULED` its slot's `reserved_count` drops by one and `slot_id` clears. Separately, an `AssignmentEditor` may link a `PUBLISHED` or `RETRACTED` story to a live follow-up by supplying `superseding_story_id`; the target of the link must exist (`ERR_STORY_NOT_FOUND`), must differ from the story being linked, and must reference a non-terminal story — where terminal means exactly `RETRACTED` or `KILLED`, so a `PUBLISHED` story may itself serve as the follow-up target — violations of the latter two rules are rejected with `ERR_VALIDATION` (HTTP 400), while attempting the link on a story that is neither `PUBLISHED` nor `RETRACTED` yields `ERR_INVALID_STATE`. The link is recorded in `superseded_by_story_id` and increments the story's `version`.

Finally, a `ManagingEditor` may cancel a slot that is still `ACTIVE`, moving it to `CANCELLED` — but only when its `reserved_count` is zero; cancelling a slot with reservations outstanding is rejected with `ERR_SLOT_NOT_EMPTY` (HTTP 409).

### 3.6. Corrections, Issuance, and Retraction

Accountability continues after publication. Any of the seven desk-side roles may propose a correction on a story — but only while the story is `PUBLISHED`; proposing against any other state is rejected with `ERR_STORY_NOT_PUBLISHED` (HTTP 409). The proposal carries a `severity` of `MINOR`, `MAJOR`, or `RETRACTION` and the public `correction_text`; the server records the proposer in `proposer_staff_id` from `X-User-ID`, the correction's `story_id` comes from the path, and it lands in `PROPOSED` status with `approver_staff_id`, `correction_number`, and `issued_at` all unset.

A `ManagingEditor` then governs the queue. Approval moves a `PROPOSED` correction to `APPROVED` and records the approver in `approver_staff_id` — but the approver must not be the proposer, per §2.9's segregation rule. Rejection moves it to `REJECTED`. Both bump the correction's `version`, and both are rejected with `ERR_INVALID_STATE` once the correction has left `PROPOSED`.

Issuance is the point of no return. A `ManagingEditor` issues an `APPROVED` correction, and the story must still be `PUBLISHED` at that instant — otherwise `ERR_STORY_NOT_PUBLISHED`. Issuance assigns the `correction_number`: the count of the story's previously issued corrections plus one, evaluated at the instant of issue, so numbers are per-story chronological and gap-free; the story `version` bump in the same act serializes concurrent issuance. The correction's `issued_at` is stamped with the logical clock, its `version` increments, and the story's `correction_count` rises by one; the story's `version` increments exactly once per issuance, even when the issuance also retracts the story and voids its analytics reports.

Severity decides what happens next. `MINOR` and `MAJOR` corrections simply stand on the record. Issuing a correction whose `severity` is `RETRACTION` triggers a two-hop cascade: first the story moves `PUBLISHED → RETRACTED` with its `version` incremented; then every analytics report on that story still in `ACTIVE` status is voided, moving to `VOID` (§3.7).

### 3.7. Audience Analytics and the Author Track Record

Once a story is published, the audience desk measures it. An `AnalyticsProducer` ingests an analytics report for a `PUBLISHED` story — ingestion against any other state is rejected with `ERR_STORY_NOT_PUBLISHED` — supplying a `variant` of `REALTIME` or `SETTLED`, the measurement window `window_start` to `window_end` (end strictly after start, else `ERR_INVALID_INTERVAL`), the measured `views`, and the measured `engagement_minutes`, both non-negative. Measurement windows are unique per story and variant: if a report already exists for the same story, the same `variant`, and the same `window_end` — regardless of that existing report's status, so a `VOID` report still blocks re-ingestion of its window — the ingestion is rejected with `ERR_DUPLICATE_ANALYTICS_WINDOW` (HTTP 409). A report opens in `ACTIVE` status, and retraction of the story voids every still-active report (§3.6).

Scoring follows a pinned three-stage order that breaks the apparent circularity between the raw score and the tier. Stage one computes `raw_score`: six points per view plus four points per engagement minute, the total divided by 100, rounded half-up to two decimal places. Stage two derives the `tier` from the raw score alone: `A` when the raw score is at least 100, otherwise `B` when it is at least 40, otherwise `C`. Stage three applies the tier multiplier — 1.25 for tier `A`, 1.0 for tier `B`, 0.8 for tier `C`. For the `SETTLED` variant, the report's `performance_score` is the raw score times the tier multiplier, rounded half-up to two decimal places. For the `REALTIME` variant, an additional dampening applies — the raw score times the tier multiplier times 0.9, rounded half-up to two decimal places — so identical in-flight measurements score lower than their settled counterparts.

These scores feed back into assignment-desk prioritization through the author's track record. For a given author, consider only analytics reports that are `ACTIVE`, of the `SETTLED` variant, and attached to stories authored by that staff member whose status is `PUBLISHED` or `RETRACTED`; realtime and voided reports are excluded. If no qualifying reports exist, the track record is 0; otherwise it is the arithmetic mean of their `performance_score` values, rounded half-up to two decimal places. The analytics-blend variant of the story priority score — returned by the computed priority-score read of §3.2 when its `variant` parameter selects `ANALYTICS` — recomputes the desk base score and then mixes it with the author's track record: six-tenths of the base plus four-tenths of the track record, the sum rounded half-up to two decimal places. The stored `priority_score` is never rewritten by this blend; it remains the desk-forward figure used by the bump check.

### 3.8. Breaking News: Declaration, the Bump Cascade, and Staffing Call-Ins

When the news will not wait, a `NewsDirector` declares a breaking-news event with a `title`, a `priority_band` of 1, 2, or 3, a coverage window from `window_start` to `window_end` (end strictly after start, else `ERR_INVALID_INTERVAL`), and an optional `call_in_pool_size` — the number of staff to page on activation — which defaults to 2 and may be zero. The event records the declaring operator's opaque header identity in `declared_by` and opens in `DECLARED` status. Events are listable by the `NewsDirector`, `AssignmentEditor`, and `ManagingEditor` with a `status` filter, and each event exposes its paged call-ins and the assignments it bumped as reverse collections readable by the `NewsDirector`.

Activation is the override. A `NewsDirector` activates a `DECLARED` event — any other state yields `ERR_INVALID_STATE` — and the system executes a three-hop cascade. Hop one bumps assignments: every `ACCEPTED` assignment whose half-open window intersects the event's window — the assignment's `start_at` falls before the event's `window_end` and its `end_at` falls after the event's `window_start` — and whose story's `priority_score` sits strictly below the bump floor for the event's `priority_band` moves to `BUMPED`. The floor is 9,999 for band 1 (which clears essentially everything in the window), 60 for band 2, and 30 for band 3. Each bumped assignment records the event in `bumped_by_event_id`, and each affected staff member's `active_assignment_count` is recomputed down by one. Hop two re-evaluates each bumped story — that is, each story that lost at least one assignment to hop one; stories untouched by hop one are never re-evaluated: if the story now has zero `REPORTER` assignments in `PROPOSED` or `ACCEPTED`, it moves from its current pre-publication state — `DRAFT`, `IN_EDIT`, `FACT_CHECK`, `LEGAL_REVIEW`, `CLEARED`, or `SCHEDULED` — to `ON_HOLD`, incrementing its `version`; §3.3's bubble-up describes how a later reporter acceptance resumes it. Hop three releases capacity: each such held story that was `SCHEDULED` drops its slot — the slot's `reserved_count` falls by one and the story's `slot_id` clears. Activation also increments the event's `version`.

Independently of the bump cascade, activation pages a staffing call-in pool. Eligible staff are those whose `employment_status` is `ACTIVE` and whose `role_capability` is `REPORTER` or `PHOTOGRAPHER`. They are ranked by `active_assignment_count` ascending, ties broken by `created_at` ascending and any remaining ties by staff creation order — the least-loaded, then the longest-serving record first — and up to `call_in_pool_size` of them are paged. Each page creates a `StaffCallIn` in `PAGED` status, in ranking order, recording the `event_id` and `staff_id`, stamping `paged_at` with the logical clock, and setting `expires_at` sixty minutes after the page. An empty eligible pool simply produces zero call-ins and the activation still succeeds.

Paged staff answer for themselves — `Reporter` or `Photographer` roles whose `X-User-ID` equals the call-in's `staff_id`, with `ERR_FORBIDDEN` otherwise — and only a `PAGED` call-in can be answered (`ERR_INVALID_STATE`). Confirming moves the call-in `PAGED → CONFIRMED`; declining moves it `PAGED → DECLINED`; either bumps its `version`. Both answers must arrive before `expires_at`: a late answer finds the call-in auto-transitioned to `EXPIRED` and is rejected with `ERR_CALL_IN_EXPIRED` (HTTP 409). Expiry also arrives on its own: the operations checkpoint of §3.5 expires every `PAGED` call-in whose `expires_at` has been reached, and resolving the event does the same for its outstanding pages.

Resolution closes the event. A `NewsDirector` resolves an `ACTIVE` event — any other state yields `ERR_INVALID_STATE` — stamping `resolved_at` with the logical clock, moving every still-`PAGED` call-in of the event to `EXPIRED`, and incrementing the event's `version`. `RESOLVED` is terminal: the event's bump decisions stand, and any crewing the newsroom wants back must be rebuilt through ordinary assignment proposals.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a distinct new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including all state transitions and field edits — and all reads return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/newsroom/staff` | Create a staff member | NewsDirector |
| GET | `/newsroom/staff` | List staff with filters and pagination | AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/staff/{id}` | Read one staff member | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer |
| PATCH | `/newsroom/staff/{id}` | Update employment status, assignment cap, or hourly rate | NewsDirector |
| GET | `/newsroom/staff/{id}/assignments` | List assignments of a staff member | AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/staff/{id}/payroll` | Weekly payroll snapshot for a staff member | ManagingEditor, NewsDirector |
| GET | `/newsroom/staff/{id}/reviews` | List review verdicts filed by a staff member | AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/staff/{id}/corrections` | List corrections proposed or approved by a staff member | ManagingEditor, NewsDirector |
| GET | `/newsroom/staff/{id}/call-ins` | List staffing call-ins of a staff member | NewsDirector |
| POST | `/newsroom/pitches` | Submit a story pitch | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor |
| GET | `/newsroom/pitches` | List pitches with filters | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/pitches/{id}` | Read one pitch | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/pitches/{id}/stories` | List stories spawned from a pitch | AssignmentEditor, ManagingEditor, NewsDirector |
| POST | `/newsroom/pitches/{id}/start-review` | Move a submitted pitch into desk review | AssignmentEditor |
| POST | `/newsroom/pitches/{id}/return` | Return a pitch to the submitter for rework | AssignmentEditor |
| POST | `/newsroom/pitches/{id}/greenlight` | Greenlight a pitch and spawn its story | AssignmentEditor |
| POST | `/newsroom/pitches/{id}/reject` | Reject a pitch under desk review | AssignmentEditor |
| POST | `/newsroom/pitches/{id}/withdraw` | Withdraw an own pitch | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor |
| GET | `/newsroom/stories` | List stories with filters | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer |
| GET | `/newsroom/stories/{id}` | Read one story | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer |
| PATCH | `/newsroom/stories/{id}` | Edit a story's word count or embargo (author only, early states) | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor |
| POST | `/newsroom/stories/{id}/submit-edit` | Submit a draft story for editing | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor |
| POST | `/newsroom/stories/{id}/complete-edit` | Complete the edit and advance to fact-check | CopyEditor |
| POST | `/newsroom/stories/{id}/reviews` | File a fact-check or legal verdict on a story | FactChecker, LegalReviewer |
| POST | `/newsroom/stories/{id}/schedule` | Schedule a cleared story into a publication slot | AssignmentEditor |
| POST | `/newsroom/stories/{id}/unschedule` | Remove a story from its slot | AssignmentEditor |
| POST | `/newsroom/stories/{id}/reopen` | Reopen a cleared story as a major revision | ManagingEditor |
| POST | `/newsroom/stories/{id}/kill` | Kill a pre-publication story | ManagingEditor |
| POST | `/newsroom/stories/{id}/supersede` | Link a published story to a live follow-up | AssignmentEditor |
| GET | `/newsroom/stories/{id}/priority-score` | Computed read of a story's priority score | AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/stories/{id}/assignments` | List assignments on a story | AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/stories/{id}/reviews` | List review records of a story | CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector |
| GET | `/newsroom/stories/{id}/corrections` | List corrections of a story | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer |
| GET | `/newsroom/stories/{id}/analytics-reports` | List analytics reports of a story | AnalyticsProducer, AssignmentEditor, ManagingEditor, NewsDirector |
| POST | `/newsroom/stories/{id}/corrections` | Propose a correction on a published story | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor |
| POST | `/newsroom/stories/{id}/analytics-reports` | Ingest an analytics measurement for a published story | AnalyticsProducer |
| POST | `/newsroom/assignments` | Propose a reporter or photographer assignment | AssignmentEditor |
| POST | `/newsroom/assignments/{id}/accept` | Accept a proposed assignment | Reporter, Photographer |
| POST | `/newsroom/assignments/{id}/decline` | Decline a proposed assignment | Reporter, Photographer |
| POST | `/newsroom/assignments/{id}/complete` | Complete an accepted assignment with actual minutes | Reporter, Photographer, AssignmentEditor |
| POST | `/newsroom/assignments/{id}/cancel` | Cancel a proposed or accepted assignment | AssignmentEditor |
| POST | `/newsroom/slots` | Open a publication slot | AssignmentEditor, ManagingEditor |
| GET | `/newsroom/slots` | List publication slots | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer |
| GET | `/newsroom/slots/{id}` | Read one publication slot | Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer, AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer |
| GET | `/newsroom/slots/{id}/stories` | List stories scheduled in a slot | AssignmentEditor, ManagingEditor, NewsDirector |
| POST | `/newsroom/slots/{id}/cancel` | Cancel an empty publication slot | ManagingEditor |
| POST | `/newsroom/corrections/{id}/approve` | Approve a proposed correction | ManagingEditor |
| POST | `/newsroom/corrections/{id}/reject` | Reject a proposed correction | ManagingEditor |
| POST | `/newsroom/corrections/{id}/issue` | Issue an approved correction | ManagingEditor |
| POST | `/newsroom/breaking-events` | Declare a breaking-news event | NewsDirector |
| GET | `/newsroom/breaking-events` | List breaking-news events | NewsDirector, AssignmentEditor, ManagingEditor |
| GET | `/newsroom/breaking-events/{id}` | Read one breaking-news event | NewsDirector, AssignmentEditor, ManagingEditor |
| POST | `/newsroom/breaking-events/{id}/activate` | Activate an event, running the bump cascade and call-in pages | NewsDirector |
| POST | `/newsroom/breaking-events/{id}/resolve` | Resolve an active event and expire its pages | NewsDirector |
| GET | `/newsroom/breaking-events/{id}/call-ins` | List call-ins paged for an event | NewsDirector |
| GET | `/newsroom/breaking-events/{id}/assignments` | List assignments bumped by an event | NewsDirector |
| POST | `/newsroom/call-ins/{id}/confirm` | Confirm a paged call-in before expiry | Reporter, Photographer |
| POST | `/newsroom/call-ins/{id}/decline` | Decline a paged call-in before expiry | Reporter, Photographer |
| POST | `/newsroom/ops/run-publication-scheduler` | Run the publication and call-in-expiry checkpoint | NewsDirector |
| POST | `/_clock/set_current_utc` | Advance the logical clock | NewsDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_PITCH_NOT_FOUND` | 404 Not Found |
| `ERR_STORY_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CORRECTION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CALL_IN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STORY_NOT_PUBLISHED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_NO_REPORTING_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_STAFF_INACTIVE` | 422 Unprocessable Entity |
| `ERR_CAPABILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CHANNEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_EMBARGO_BEYOND_SLOT` | 422 Unprocessable Entity |
| `ERR_CALL_IN_EXPIRED` | 409 Conflict |
| `ERR_STAFF_TIME_CONFLICT` | 409 Conflict |
| `ERR_SLOT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_ANALYTICS_WINDOW` | 409 Conflict |
| `ERR_SLOT_NOT_EMPTY` | 409 Conflict |
| `ERR_PITCH_REWORK_LIMIT` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
