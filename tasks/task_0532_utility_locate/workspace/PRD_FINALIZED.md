# Utility Locate API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Utility Locate API, a digital "811 — Call Before You Dig" platform that coordinates the safe excavation of ground where buried utility lines may be present. Before anyone breaks ground, an excavation contractor must give notice, every facility owner whose buried infrastructure lies under the proposed dig site must be told, and each of those owners must post back an explicit all-clear (a "positive response") before painting or flagging their lines. The platform models this multi-party choreography end to end: it accepts a locate ticket describing a dig site as a rectangular area on a shared coordinate grid, routes notifications to exactly the member utilities whose service areas overlap that dig site, tracks a response deadline (the SLA clock) against which every owner must answer, and dispatches field technicians to mark the ground once all owners have cleared the site.

A locate ticket only clears when every notified member unanimously reports no conflict; a single conflicting owner holds the whole dig hostage until it is resolved. The API therefore treats the ticket's posture as a derived aggregate over its children rather than a value that any single actor sets directly. Layered on top of that core negotiation are the temporal mechanics that make locate work legally binding: a positive-response deadline, a mark-out validity window that governs how long paint stays legally fresh, and a re-mark ("refresh") cycle that slides that window forward. Because these deadlines are enforced against a logical clock rather than wall-clock time, the platform is fully test-drivable — an operator can advance the clock and observe the system fire its due auto-transitions deterministically. The final concern the platform addresses is accountability: when a line is nonetheless struck, a damage report apportions repair liability between the excavator and the facility owner according to whether valid marks were in force and whether the excavator dug within them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header, or carrying a value the server cannot validate, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles: `Excavator`, `FacilityOwner`, `LocateTech`, `CallCenter`, and `Admin`.

Three of these roles are entity-backed, meaning `X-User-ID` names a specific persisted record and is used for ownership checks. When `X-User-Role` is `Excavator`, `X-User-ID` is the `id` of the acting `Excavator`; any ownership check on a resource that references an excavator (for example, disputing a damage report whose parent ticket carries a given `excavator_id`) compares that resource's excavator foreign key to `X-User-ID`. When `X-User-Role` is `FacilityOwner`, `X-User-ID` is the `id` of the acting `MemberUtility`; ownership checks on any resource that references a member utility (a notification's `member_utility_id`, a meet request's `member_utility_id`, a damage report's `member_utility_id`) compare that resource's member foreign key to `X-User-ID`. When `X-User-Role` is `LocateTech`, `X-User-ID` is the `id` of the acting `LocateTech`; ownership checks on an assignment or on a mark-out compare the assignment's `locate_tech_id` to `X-User-ID`.

The remaining two roles are operational and carry an opaque identity. When `X-User-Role` is `CallCenter`, `X-User-ID` is an opaque call-center-operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Admin`, `X-User-ID` is likewise an opaque administrator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses include the following fields inside the response envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of server-managed fields. Every resource receives an `id`, a unique server-minted UUID with no type prefix, and a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. Resources that can change after creation additionally carry an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and a `version` (an integer that starts at its initial value and increments by one on every mutation). The `version` field underpins the optimistic-concurrency mechanism described in §2.11.

One entity is a deliberate exception: a `PositiveResponse` is an append-only, immutable record. Once a facility owner posts it, it is never modified. A `PositiveResponse` therefore carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field.

### 2.5. Consistency, Cascades, and Derived Reconciliation

The `LocateTicket` is a compound aggregate: its `response_posture` and the counters that support it are never set directly by a client but are always recomputed from the ticket's child `UtilityNotification` rows. Whenever a child changes in a way that affects the parent — a member posts a positive response, the clock advances past a deadline — the system reconciles the parent so that the aggregate always reflects the true state of its children. Each such reconciliation that mutates a resource refreshes that resource's `updated_at` and increments its `version`.

Cascades also flow the other way. When a parent transition renders dependent work moot, the system resolves that work as part of the same operation rather than leaving orphaned child resources behind. These cascades are described in full in the workflow narratives of §3; the governing principle is that a single client action may legitimately mutate several resources at once, and every one of those mutations is part of the operation's contract.

### 2.6. Nested Resource Retrieval and Reference Validation

Several list endpoints are reverse-reachability views that scope their results to a parent — for instance, the notifications, mark-outs, meet requests, and damage reports that belong to a given ticket. When a request carries one or more resource identifiers, whether in the URL path or as a foreign-key field in the body, the server validates them left to right and in order. The first identifier that does not resolve to an existing resource causes the request to be rejected immediately with the matching not-found error (`ERR_TICKET_NOT_FOUND`, `ERR_MEMBER_UTILITY_NOT_FOUND`, `ERR_LOCATE_TECH_NOT_FOUND`, `ERR_EXCAVATOR_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_MARKOUT_NOT_FOUND`, `ERR_MEET_REQUEST_NOT_FOUND`, or `ERR_DAMAGE_REPORT_NOT_FOUND`, as appropriate), before any downstream state or business rule is evaluated.

### 2.7. The Shared Coordinate Grid and Routing Predicate

Every dig site and every member utility's service area is expressed as an axis-aligned rectangle on a single shared integer grid, given as `{min_x, min_y, max_x, max_y}`. A ticket's dig-site rectangle is its `dig_polygon`; a member utility's service area is its `service_polygon`. A valid rectangle must have `max_x` strictly greater than `min_x` and `max_y` strictly greater than `min_y`.

Routing decides which members hear about a dig. A ticket routes to a member if and only if their two rectangles overlap on open interiors along both axes: the dig rectangle's left edge lies strictly left of the service rectangle's right edge, the service rectangle's left edge lies strictly left of the dig rectangle's right edge, the dig rectangle's bottom edge lies strictly below the service rectangle's top edge, and the service rectangle's bottom edge lies strictly below the dig rectangle's top edge. All four conditions must hold. Rectangles that merely touch along an edge — for example, where a service rectangle's left edge exactly equals the dig rectangle's right edge — do not overlap and do not route. Only members whose `status` is `ACTIVE` are ever routed a notification; `INACTIVE` members are skipped entirely.

### 2.8. The Logical Clock and Deferred Actions

The platform runs against a logical clock rather than real wall-clock time. Before any client sets it, the clock reads `2026-05-01T00:00:00Z`. An operator may set the clock to any absolute UTC instant by supplying the target instant as `to_iso8601`. Advancing the clock is not a passive act: when the clock moves forward past a ticket's positive-response deadline, past an assignment's field-completion deadline, or past a ticket's dig-window expiry, the system fires the corresponding due auto-transitions. These are the scheduled, deferred actions of the system — a ticket may expire or breach its SLA, an assignment may breach, and a mark-out may expire — all triggered as a side effect of the clock advancing rather than by an explicit request against those resources. The precise conditions for each auto-transition live in the §3 workflow narratives that own them.

### 2.9. Time Windows, Deadlines, and Precision

All computed instants — the positive-response deadline (`sla_due_at`), mark-out validity (`valid_until`), assignment deadlines (`sla_deadline_at`), dig-window boundaries (`dig_window_opens_at`, `dig_window_expires_at`), and the other clock-stamped computed fields (`markout_completed_at`, `due_at`, `responded_at`, `dispatched_at`, `completed_at`) — are datetimes evaluated at second granularity. Where a window is computed forward from a base instant, the base instant's time-of-day is preserved. When these computed-instant fields are serialized on a resource, they are rendered as ISO 8601 UTC at second granularity, with no fractional digits and a trailing `Z` (for example, `2026-05-01T00:00:00Z`) — distinct from the audit timestamps `created_at` and `updated_at` of §2.4, which carry three fractional digits.

### 2.10. Monetary Apportionment and Rounding

Repair costs and liability shares are handled entirely in integer cents. Where an apportionment multiplies a cost by a percentage, that product is rounded to the nearest whole cent using the round-half-up convention (a value at exactly the halfway point rounds up). The complementary share is then taken as the exact integer remainder so that the two shares always sum back to the original cost with no drift. The specific apportionment tiers are described in §3.8.

### 2.11. Optimistic Concurrency Control for Mark-Out Refresh

A re-mark (refresh) supersedes a prior completed mark-out and slides the ticket's dig window forward; because that bubble-up advances the ticket's `version`, the platform guards refresh creation with an optimistic-concurrency check on the parent ticket. A request that creates a refresh mark-out (one whose `supersedes_markout_id` is set) must carry `expected_ticket_version` holding the `version` of the target `LocateTicket` that the client last observed. If that value does not match the ticket's current `version` — meaning another writer has already posted a refresh and advanced the ticket's version since the client last read it — the create is rejected with `ERR_STALE_TICKET_VERSION` (HTTP 412), because the client's view of which mark-out it may supersede is no longer current. Mark-out creation on the first (non-refresh) path does not carry or check `expected_ticket_version`; no other endpoint in the system takes a version field.

## 3. Business Logic & Workflows

### 3.1. Registering the Parties

Before any dig is filed, the operational participants are registered. A `CallCenter` operator (or an `Admin`) registers an **Excavator** — a digging contractor — by supplying a `company_name`, a `contact_email` (unique among excavators), and a `state_code`, the two-letter state abbreviation such as `CA`. A newly registered excavator begins with `status` `ACTIVE`. An `Admin` may later suspend an excavator, moving its `status` to `SUSPENDED`; a suspended excavator can no longer file dig notices.

A `CallCenter` operator or `Admin` registers a **MemberUtility** — a facility owner — with a `name`, a `facility_type`, a `service_polygon`, and an optional `emergency_contact_minutes`. The `facility_type` is one of `GAS`, `ELECTRIC`, `WATER`, `SEWER`, `TELECOM`, or `OIL`; of these, `GAS` and `OIL` are the high-priority facility types, which later tighten dispatch deadlines and conflict handling. The `emergency_contact_minutes` value is the response window in minutes the member commits to for emergency tickets and defaults to 60 when omitted. A member begins with `status` `ACTIVE`; an `Admin` may deactivate it, setting `status` to `INACTIVE`, after which the member is no longer routed notifications.

**LocateTech**nicians are registered by a `CallCenter` operator or `Admin` against a specific member utility. Registration supplies the tech's `full_name`, the `member_utility_id` of the facility owner they perform mark-outs for, and `certified_facility_types` — the list of facility-type values (drawn from the same six enum members) the tech is qualified to mark. A new tech begins with `status` `AVAILABLE` and an `active_assignment_count` of 0; that count is a read-only field tracking how many of the tech's assignments are currently in the `DISPATCHED` or `EN_ROUTE` state. An `Admin` or `CallCenter` operator may take a tech off duty, moving `status` to `OFF_DUTY`; an off-duty tech cannot be dispatched.

### 3.2. Filing and Submitting a Dig Ticket

An `Excavator` (or a `CallCenter` operator filing on their behalf) opens the process by creating a **LocateTicket**. Creation supplies the `excavator_id` of the filer, a `ticket_type` of either `NORMAL` or `EMERGENCY`, the `dig_polygon` describing the dig site, a free-text `work_description`, and an optional `is_white_lined` flag (defaulting to false) that indicates the excavator has already pre-marked — "white-lined" — the dig site. A freshly created ticket sits in `INTAKE` with a `response_posture` of `INTAKE`; the `dig_polygon` must be a valid rectangle, and a malformed box is rejected with `ERR_INVALID_GEOMETRY`.

Submitting the ticket is the pivotal event that starts the whole negotiation, advancing it from `INTAKE` to `SUBMITTED`. Submission is only allowed while the ticket is still in `INTAKE`; otherwise it is rejected with `ERR_TICKET_NOT_IN_INTAKE`. Four preconditions guard submission and are evaluated in this order: first the ticket-state check just described (`ERR_TICKET_NOT_IN_INTAKE`); then the filing excavator's `status` must be `ACTIVE`, or the submission is rejected with `ERR_EXCAVATOR_SUSPENDED`; then at least one `ACTIVE` member utility's `service_polygon` must overlap the `dig_polygon` under the routing predicate of §2.7, failing which the submission is rejected with `ERR_NO_MEMBERS_IN_AREA`; and finally, if the ticket is `NORMAL` and not white-lined, a `MeetRequest` for this ticket must already exist in one of the states `REQUESTED`, `SCHEDULED`, or `COMPLETED`, failing which the submission is rejected with `ERR_MEET_REQUEST_REQUIRED`. An `EMERGENCY` ticket, or a `NORMAL` ticket whose `is_white_lined` is true, is exempt from that meet-request requirement.

When submission succeeds, several things happen together. The system computes the positive-response deadline `sla_due_at` (see §3.3), and sets the earliest legal dig start `dig_window_opens_at` equal to that same `sla_due_at`. It then creates exactly one `UtilityNotification` for each `ACTIVE` member whose service area overlaps the dig site: each notification starts in `PENDING` `response_status`, copies the ticket's `sla_due_at` into its own `due_at`, and records `is_high_priority` as true when that member's `facility_type` is `GAS` or `OIL` and false otherwise. The ticket's `notified_member_count` is set to the number of notifications created and `open_response_count` is set to the same value. Finally the ticket's `response_posture` is recomputed to `AWAITING_RESPONSES`. This is a direct fan-out: one submit action creates all N notifications at once.

An excavator may cancel a ticket while it is in `INTAKE` or `SUBMITTED`; a cancel attempt in any other state is rejected with `ERR_TICKET_NOT_CANCELLABLE`. Cancelling from `SUBMITTED` carries an additional guard: it is blocked with `ERR_ASSIGNMENT_ACTIVE` if any `LocateAssignment` for the ticket is currently `DISPATCHED` or `EN_ROUTE`. When a cancel succeeds the ticket moves to `CANCELLED`; any still-`PENDING` notifications remain `PENDING` (no member may answer a cancelled ticket) and, as a cascade, every open `MeetRequest` for the ticket — those in `REQUESTED` or `SCHEDULED` — is moved to `DECLINED`.

### 3.3. Computing the Positive-Response Deadline

The deadline `sla_due_at` is computed at the instant of submission from just two inputs — the `ticket_type` and the logical-clock instant of submit — and never depends on how members later respond. For an `EMERGENCY` ticket the window is a flat wall-clock span: the deadline is the submit instant plus two hours, and weekend days are counted normally within that span. For a `NORMAL` ticket the window is measured in business days and skips whole non-business days: starting from the submit instant, the cursor advances one calendar day at a time, keeping the same time-of-day as the submit instant, and each day that lands on Monday through Friday decrements a counter that begins at two business days, while each day that lands on Saturday or Sunday advances the cursor without decrementing the counter. When the counter reaches zero the cursor is the deadline. In both variants `dig_window_opens_at` is then set equal to `sla_due_at`, establishing the earliest legal moment the excavator may begin digging.

### 3.4. Positive Responses and the All-Clear Quorum

Once a ticket is `SUBMITTED`, each notified facility owner must answer their `UtilityNotification` by posting a **PositiveResponse**. The owner supplies the `notification_id` being answered, an `outcome` of `CLEAR`, `CONFLICT`, or `MARKED_BY_OWNER`, and an optional free-text `comment`. Posting is permitted only while the parent ticket is `SUBMITTED` (otherwise `ERR_TICKET_NOT_ACCEPTING_RESPONSES`) and only while the target notification is still `PENDING` (otherwise `ERR_NOTIFICATION_ALREADY_ANSWERED`); the acting `FacilityOwner` must own the notification's `member_utility_id`, or the request is rejected with `ERR_NOT_NOTIFICATION_OWNER`.

Each successful post creates an immutable positive-response record. The record stamps `responded_at` with the logical-clock instant of the post and sets `was_late` to true exactly when `responded_at` is strictly after the notification's `due_at`. All three outcomes are handled with equal weight and each drives the notification to a terminal state and bubbles up to the ticket. A `CLEAR` outcome moves the notification's `response_status` to `CLEAR`; a `MARKED_BY_OWNER` outcome moves it to `MARKED_BY_OWNER` and, like `CLEAR`, counts as a cleared leg for quorum purposes; a `CONFLICT` outcome moves it to `CONFLICT`. In every case the ticket's `open_response_count` is decreased by one and the ticket's `response_posture` is recomputed. For a `CLEAR` or `MARKED_BY_OWNER` response, if the open count has now reached zero and no notification is in `CONFLICT`, the ticket advances from `SUBMITTED` to `RESPONSES_COMPLETE`. For a `CONFLICT` response the posture becomes `CONFLICT`, and that conflict blocks the ticket from reaching `RESPONSES_COMPLETE` even once the open count hits zero — a single unresolved conflict holds the whole dig.

The `response_posture` itself is a derived aggregate computed over the ticket's notifications in a fixed precedence, where the first matching branch wins. If the ticket is still in `INTAKE`, the posture is `INTAKE`. Otherwise, if the clock has advanced strictly past `sla_due_at` and at least one notification is still `PENDING`, the posture is `SLA_BREACHED`. Otherwise, if at least one notification is in `CONFLICT`, the posture is `CONFLICT`. Otherwise, if at least one notification is still `PENDING`, the posture is `AWAITING_RESPONSES`. Otherwise — every notification answered and none in conflict — the posture is `ALL_CLEAR`. Alongside this, `open_response_count` always equals the number of notifications still in `PENDING`.

### 3.5. SLA Expiry Under the Clock

The positive-response deadline is enforced by the clock. When the clock is advanced strictly past a submitted ticket's `sla_due_at` while at least one notification remains `PENDING` (that is, `open_response_count` is greater than zero), the ticket auto-transitions from `SUBMITTED` to `EXPIRED` and its `response_posture` is recomputed to `SLA_BREACHED`. Each still-pending notification keeps its `PENDING` `response_status`, but the ticket is now expired and no member may respond to it any longer. A ticket that has already reached `RESPONSES_COMPLETE` before the deadline is not expired by the clock.

### 3.6. Dispatching Technicians and the Field SLA

Once a member has a leg to work, a `FacilityOwner` (or a `CallCenter` operator) dispatches a technician by creating a **LocateAssignment** against a specific notification. The create supplies the `ticket_id`, the `notification_id` the assignment services, and the `locate_tech_id` of the technician being sent. On success the assignment stamps `dispatched_at` with the current clock, begins in `DISPATCHED`, and the technician's `active_assignment_count` is incremented by one. Two safety gates guard dispatch, evaluated after the ownership and existence checks: the dispatched tech's `status` must be `AVAILABLE` and not `OFF_DUTY`, or the create is rejected with `ERR_TECH_OFF_DUTY`; and the tech's `certified_facility_types` must include the notified member's `facility_type`, or the create is rejected with `ERR_TECH_NOT_CERTIFIED`.

The field-completion deadline `sla_deadline_at` is computed at dispatch from three inputs — the ticket's `ticket_type`, the notification's `is_high_priority` flag, and the tech's `active_assignment_count` as it stood immediately before this dispatch incremented it — in a pinned order. The base number of minutes is the member's `emergency_contact_minutes` when the ticket is `EMERGENCY`, and 240 minutes when the ticket is `NORMAL`. If the notification is high priority, that minute figure is multiplied by one-half and rounded up to the next whole minute; this high-priority tightening is applied first. Then, if the tech's pre-dispatch `active_assignment_count` was three or more, a fixed 60 minutes of slack is added afterward. The resulting minute count is added to `dispatched_at` to yield `sla_deadline_at`.

A technician advances their own assignment. Going en route moves the assignment from `DISPATCHED` to `EN_ROUTE`; it requires the assignment to be in `DISPATCHED` (otherwise `ERR_ASSIGNMENT_NOT_DISPATCHED`) and the acting tech to own it (otherwise `ERR_NOT_ASSIGNMENT_TECH`). Completing the assignment moves it from `EN_ROUTE` to `COMPLETED`; it requires the assignment to be in `EN_ROUTE` (otherwise `ERR_ASSIGNMENT_NOT_EN_ROUTE`), the acting tech to own it (otherwise `ERR_NOT_ASSIGNMENT_TECH`), and a `MarkOut` for this assignment to already be in `COMPLETE` (otherwise `ERR_MARKOUT_NOT_COMPLETE`). On completion the assignment stamps `completed_at` with the clock, sets `sla_breached` to true exactly when `completed_at` is strictly after `sla_deadline_at`, moves to `COMPLETED`, and decrements the tech's `active_assignment_count` by one.

A `FacilityOwner` (or `CallCenter` operator) may cancel an assignment while it is in `DISPATCHED` or `EN_ROUTE`; a cancel in any other state is rejected with `ERR_ASSIGNMENT_NOT_CANCELLABLE`. Cancellation moves the assignment to `CANCELLED`, decrements the tech's `active_assignment_count` by one, and as a cascade moves any `IN_PROGRESS` `MarkOut` for that assignment to `EXPIRED`.

The field deadline is also enforced by the clock. When the clock advances strictly past an assignment's `sla_deadline_at` while the assignment is still in `DISPATCHED` or `EN_ROUTE`, the assignment auto-transitions to `BREACHED`, its `sla_breached` flag is set to true, and the tech's `active_assignment_count` is decremented by one. This clock-driven breach applies identically whether the assignment was sitting in `DISPATCHED` or in `EN_ROUTE`.

### 3.7. Marking the Ground and Refreshing the Marks

A `LocateTech` places paint and flags by creating a **MarkOut**. The create supplies the `assignment_id` the tech performed, the `ticket_id` (denormalized for reverse lookup), and a `marks_count` of the number of marks placed, which must be at least 1 or the create is rejected with `ERR_INVALID_GEOMETRY`. A first mark-out leaves `supersedes_markout_id` empty; a refresh sets it to the `id` of the prior mark-out being replaced. The mark-out's `is_refresh` flag is computed true exactly when `supersedes_markout_id` is present. A new mark-out begins in `IN_PROGRESS`.

Completing a mark-out moves it from `IN_PROGRESS` to `COMPLETE`. Completion requires the mark-out to be in `IN_PROGRESS` (otherwise `ERR_MARKOUT_NOT_IN_PROGRESS`), the parent ticket's `response_posture` to be `ALL_CLEAR` — no unresolved conflict may remain — (otherwise `ERR_TICKET_NOT_ALL_CLEAR`), and the acting tech to own the parent assignment (otherwise `ERR_NOT_ASSIGNMENT_TECH`). On completion the mark-out stamps `completed_at` with the clock and sets its `valid_until` to `completed_at` plus 21 days, the mark-out validity span. This bubbles up to the ticket: the ticket's `markout_completed_at` is set to the completion instant, its `dig_window_expires_at` — the latest legal dig start — is set to that same 21-day expiry, and the ticket advances from `RESPONSES_COMPLETE` to `MARKED`.

Marks go stale, so the platform supports a re-mark cycle. To refresh, a tech creates a new mark-out whose `supersedes_markout_id` names the prior `COMPLETE` mark-out on the same ticket and completes it. A refresh may only supersede a mark-out that is currently `COMPLETE` on that ticket, and only while the ticket's dig window has not yet expired (the clock is at or before the ticket's current `dig_window_expires_at`); a refresh that violates either condition is rejected with `ERR_MARKOUT_NOT_REFRESHABLE`. Because a refresh advances the ticket, its create is additionally guarded by the optimistic-concurrency check of §2.11: it must carry `expected_ticket_version` matching the ticket's current `version`, or it is rejected with `ERR_STALE_TICKET_VERSION`. When the refresh mark-out reaches `COMPLETE`, the prior mark-out it supersedes is moved to `SUPERSEDED`; the ticket's `markout_completed_at` is reset to the refresh's completion instant and its `dig_window_expires_at` is recomputed from that new completion, sliding the window forward. The ticket stays `MARKED` throughout, now with a fresh window.

The dig window's two boundaries are resolved by a pinned evaluation order. At submit, `dig_window_opens_at` is set equal to `sla_due_at`; the expiry boundary is left undefined until marks complete. At the first mark-out completion, `markout_completed_at` is set to the clock, the mark-out's `valid_until` is set to that instant plus 21 days, and the ticket's `dig_window_expires_at` is set to that same value. On a refresh, `markout_completed_at` is reassigned to the refresh's completion instant and `dig_window_expires_at` is recomputed from it, so the window slides forward. A dig start is legal only while the clock lies at or after `dig_window_opens_at` and at or before `dig_window_expires_at`.

An excavator closes a `MARKED` ticket to record that the dig completed lawfully, advancing it from `MARKED` to `CLOSED`. Close requires the ticket to be in `MARKED` (otherwise `ERR_TICKET_NOT_MARKED`) and the clock to be at or before `dig_window_expires_at` (otherwise `ERR_DIG_WINDOW_EXPIRED`). The dig window is also policed by the clock: when the clock advances strictly past a marked ticket's `dig_window_expires_at`, the ticket auto-transitions to `EXPIRED` and, as a cascade, its active `COMPLETE` mark-out is moved to `EXPIRED`.

### 3.8. Damage Reports and Liability Apportionment

When a line is nonetheless struck, a `FacilityOwner` or `Excavator` files a **DamageReport**. The filing supplies the `ticket_id` under which the damage occurred, the `member_utility_id` of the owner whose line was hit, the `repair_cost_cents` (an integer of at least 0, or the filing is rejected with `ERR_INVALID_GEOMETRY`), the `dug_within_marks` flag asserting whether the excavation stayed inside the painted marks, and an optional `markout_id` naming the mark-out in force when the damage occurred (left absent when no active mark-out existed). The report begins in `FILED`, and its computed `excavator_liability_cents` and `member_liability_cents` are not yet apportioned.

A `FacilityOwner` who owns the report's `member_utility_id` opens review, advancing the report from `FILED` to `UNDER_REVIEW`; review requires the report to be in `FILED` (otherwise `ERR_DAMAGE_NOT_FILED`) and the owner to own it (otherwise `ERR_NOT_DAMAGE_OWNER`). Opening review is what apportions liability. If no `markout_id` was recorded — meaning no valid mark-out was in force and the excavator dug blind — the excavator bears the entire cost: `excavator_liability_cents` equals `repair_cost_cents`. If a `markout_id` was recorded, the split depends on care: when `dug_within_marks` is true, the excavator exercised care and bears only 25 percent, so `excavator_liability_cents` is `repair_cost_cents` multiplied by 0.25; when `dug_within_marks` is false, the excavator dug outside the marks and bears the majority, so `excavator_liability_cents` is `repair_cost_cents` multiplied by 0.75. In the marked cases the percentage product is rounded to the nearest whole cent using round-half-up. In every case, `member_liability_cents` is then taken as `repair_cost_cents` minus `excavator_liability_cents`, so the two shares always sum exactly to the reported cost.

From `UNDER_REVIEW`, the owner may settle the claim, moving it to `SETTLED`; settle requires the report to be in `UNDER_REVIEW` (otherwise `ERR_DAMAGE_NOT_UNDER_REVIEW`) and the acting owner to own it (otherwise `ERR_NOT_DAMAGE_OWNER`). Alternatively, the excavator who owns the parent ticket's `excavator_id` may dispute the claim, moving it to `DISPUTED`; dispute requires the report to be in `UNDER_REVIEW` (otherwise `ERR_DAMAGE_NOT_UNDER_REVIEW`) and the acting excavator to own the parent ticket (otherwise `ERR_NOT_DAMAGE_EXCAVATOR`).

### 3.9. Meet Requests and White-Lining

A field meet lets an excavator and a facility owner walk the site together, and for a `NORMAL` non-white-lined ticket a meet request is a submission prerequisite (see §3.2). An `Excavator` or `CallCenter` operator creates a **MeetRequest** naming the `ticket_id` needing the meet, the `member_utility_id` asked to attend, and a proposed window given as two minutes-from-epoch integers on the shared grid: `proposed_start_min` and `proposed_end_min`, where the end must be strictly greater than the start or the create is rejected with `ERR_INVALID_GEOMETRY`. A new meet request begins in `REQUESTED`.

The owning facility owner drives the meet's lifecycle. Scheduling advances the request from `REQUESTED` to `SCHEDULED`; it requires the request to be in `REQUESTED` (otherwise `ERR_MEET_NOT_REQUESTED`), the acting owner to own the request's `member_utility_id` (otherwise `ERR_NOT_MEET_OWNER`), and — critically — that no other `SCHEDULED` meet request for the same `member_utility_id` has a window that overlaps this one. Overlap is judged on the half-open interval from `proposed_start_min` up to but not including `proposed_end_min`, so two windows that merely touch at an endpoint do not overlap; a genuine overlap is rejected with `ERR_MEET_WINDOW_OVERLAP`. Completing a scheduled meet moves it from `SCHEDULED` to `COMPLETED` and requires the request to be in `SCHEDULED` (otherwise `ERR_MEET_NOT_SCHEDULED`) with the acting owner owning it (otherwise `ERR_NOT_MEET_OWNER`). The owner may instead decline a meet from either `REQUESTED` or `SCHEDULED`, moving it to `DECLINED`; a decline attempt from any other state is rejected with `ERR_MEET_NOT_DECLINABLE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or transition an existing resource, including the clock-setting capability, return `200 OK`. Every list and get endpoint returns `200 OK`. The table below is a routing summary only; the request payloads, response bodies, and side effects for each endpoint are specified in the §3 workflow narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/excavators` | Register an excavator | CallCenter, Admin |
| GET | `/excavators` | List excavators | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/excavators/{excavatorId}` | Get an excavator | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/excavators/{excavatorId}/suspend` | Suspend an excavator | Admin |
| POST | `/member-utilities` | Register a member utility | CallCenter, Admin |
| GET | `/member-utilities` | List member utilities | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/member-utilities/{memberUtilityId}` | Get a member utility | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/member-utilities/{memberUtilityId}/deactivate` | Deactivate a member utility | Admin |
| POST | `/locate-techs` | Register a locate technician | CallCenter, Admin |
| GET | `/locate-techs` | List locate techs (filter by member_utility_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/locate-techs/{locateTechId}` | Get a locate tech | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/locate-techs/{locateTechId}/set-off-duty` | Take a tech off duty | Admin, CallCenter |
| POST | `/locate-tickets` | Create a locate ticket in INTAKE | Excavator, CallCenter |
| GET | `/locate-tickets` | List locate tickets (filter by excavator_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/locate-tickets/{ticketId}` | Get a locate ticket | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/locate-tickets/{ticketId}/submit` | Submit a ticket: route notifications, start SLA clock | Excavator, CallCenter |
| POST | `/locate-tickets/{ticketId}/close` | Close a marked ticket within its dig window | Excavator |
| POST | `/locate-tickets/{ticketId}/cancel` | Cancel a ticket (INTAKE or SUBMITTED) | Excavator, CallCenter |
| GET | `/locate-tickets/{ticketId}/notifications` | List a ticket's notifications | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/locate-tickets/{ticketId}/mark-outs` | List a ticket's mark-outs | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/locate-tickets/{ticketId}/meet-requests` | List a ticket's meet requests | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/locate-tickets/{ticketId}/damage-reports` | List a ticket's damage reports | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/utility-notifications` | List notifications (filter by ticket_id or member_utility_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/utility-notifications/{notificationId}` | Get a notification | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/positive-responses` | Post a positive response to a notification | FacilityOwner |
| GET | `/positive-responses` | List positive responses (filter by notification_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/positive-responses/{positiveResponseId}` | Get a positive response | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/locate-assignments` | Dispatch a locate tech against a notification | FacilityOwner, CallCenter |
| GET | `/locate-assignments` | List assignments (filter by ticket_id, notification_id, locate_tech_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/locate-assignments/{assignmentId}` | Get an assignment | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/locate-assignments/{assignmentId}/en-route` | Tech marks assignment EN_ROUTE | LocateTech |
| POST | `/locate-assignments/{assignmentId}/complete` | Tech completes assignment | LocateTech |
| POST | `/locate-assignments/{assignmentId}/cancel` | Cancel an assignment | FacilityOwner, CallCenter |
| POST | `/mark-outs` | Create a mark-out (first or refresh) | LocateTech |
| GET | `/mark-outs` | List mark-outs (filter by assignment_id, ticket_id, supersedes_markout_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/mark-outs/{markOutId}` | Get a mark-out | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/mark-outs/{markOutId}/complete` | Complete a mark-out | LocateTech |
| POST | `/meet-requests` | Request a field meet / white-lining meet | Excavator, CallCenter |
| GET | `/meet-requests` | List meet requests (filter by ticket_id or member_utility_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/meet-requests/{meetRequestId}` | Get a meet request | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/meet-requests/{meetRequestId}/schedule` | Schedule a meet (overlap-checked) | FacilityOwner |
| POST | `/meet-requests/{meetRequestId}/complete` | Complete a scheduled meet | FacilityOwner |
| POST | `/meet-requests/{meetRequestId}/decline` | Decline a meet | FacilityOwner |
| POST | `/damage-reports` | File a damage report / claim | FacilityOwner, Excavator |
| GET | `/damage-reports` | List damage reports (filter by ticket_id, member_utility_id, markout_id) | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| GET | `/damage-reports/{damageReportId}` | Get a damage report | CallCenter, Admin, Excavator, LocateTech, FacilityOwner |
| POST | `/damage-reports/{damageReportId}/review` | Open review; apportion liability | FacilityOwner |
| POST | `/damage-reports/{damageReportId}/settle` | Settle the claim | FacilityOwner |
| POST | `/damage-reports/{damageReportId}/dispute` | Dispute the claim | Excavator |
| POST | `/_clock/set_current_utc` | Set the logical clock; fire due auto-transitions | Admin, CallCenter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_EXCAVATOR_NOT_FOUND` | 404 |
| `ERR_MEMBER_UTILITY_NOT_FOUND` | 404 |
| `ERR_LOCATE_TECH_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_MARKOUT_NOT_FOUND` | 404 |
| `ERR_MEET_REQUEST_NOT_FOUND` | 404 |
| `ERR_DAMAGE_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_GEOMETRY` | 422 |
| `ERR_TICKET_NOT_IN_INTAKE` | 409 |
| `ERR_EXCAVATOR_SUSPENDED` | 409 |
| `ERR_NO_MEMBERS_IN_AREA` | 422 |
| `ERR_MEET_REQUEST_REQUIRED` | 409 |
| `ERR_TICKET_NOT_MARKED` | 409 |
| `ERR_DIG_WINDOW_EXPIRED` | 409 |
| `ERR_TICKET_NOT_CANCELLABLE` | 409 |
| `ERR_TICKET_NOT_ACCEPTING_RESPONSES` | 409 |
| `ERR_TICKET_NOT_ALL_CLEAR` | 409 |
| `ERR_NOTIFICATION_ALREADY_ANSWERED` | 409 |
| `ERR_NOT_NOTIFICATION_OWNER` | 403 |
| `ERR_TECH_NOT_CERTIFIED` | 422 |
| `ERR_TECH_OFF_DUTY` | 409 |
| `ERR_ASSIGNMENT_NOT_DISPATCHED` | 409 |
| `ERR_ASSIGNMENT_NOT_EN_ROUTE` | 409 |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 |
| `ERR_ASSIGNMENT_ACTIVE` | 409 |
| `ERR_NOT_ASSIGNMENT_TECH` | 403 |
| `ERR_MARKOUT_NOT_COMPLETE` | 409 |
| `ERR_MARKOUT_NOT_IN_PROGRESS` | 409 |
| `ERR_MARKOUT_NOT_REFRESHABLE` | 409 |
| `ERR_STALE_TICKET_VERSION` | 412 |
| `ERR_MEET_NOT_REQUESTED` | 409 |
| `ERR_MEET_NOT_SCHEDULED` | 409 |
| `ERR_MEET_NOT_DECLINABLE` | 409 |
| `ERR_MEET_WINDOW_OVERLAP` | 409 |
| `ERR_NOT_MEET_OWNER` | 403 |
| `ERR_DAMAGE_NOT_FILED` | 409 |
| `ERR_DAMAGE_NOT_UNDER_REVIEW` | 409 |
| `ERR_NOT_DAMAGE_OWNER` | 403 |
| `ERR_NOT_DAMAGE_EXCAVATOR` | 403 |
