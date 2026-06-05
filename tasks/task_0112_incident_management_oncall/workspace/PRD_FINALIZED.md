# Incident Management & On-Call API — Product Requirements Document

## 1. Introduction

Modern engineering organizations live and die by how quickly they detect, route, and resolve service-affecting incidents. This document specifies an Incident Management & On-Call platform whose job is to take a freshly triggered incident, page the right human within seconds, escalate up a ladder of responders if nobody answers, and give incident commanders the tooling — war rooms, postmortems, action items — to learn from every outage. The platform sits at the intersection of three time-sensitive concerns: severity-driven service-level agreements (SLAs) that say how fast an incident must be acknowledged and resolved, an error-budget accounting system that tracks how much downtime a service has spent against its allowance, and a maintenance-window mechanism that suppresses noise during planned work.

The system is built around a central **Incident** hub that references several peer resources — the affected `Service`, the `EscalationPolicy` that governs paging, the `OnCallSchedule` rotations that determine who is on call, individual `Responder` records, and `MaintenanceWindow` declarations. An incident carries two state dimensions that evolve independently: a human-driven lifecycle (triggered, acknowledged, resolved, or suppressed) and a machine-driven escalation status (the paging ladder, which is cyclic and re-pages tier after tier and round after round until someone acknowledges or the ladder is exhausted). Because the platform's timers, shift-coverage checks, and window activations all depend on the current moment, an administrative test-driving capability lets an operator set the server's logical clock, making every time-dependent behavior deterministic and reproducible.

This document is the single authoritative contract for implementers. It defines the global request/response conventions, the role model, the precise calculation rules that drive SLA deadlines and error-budget consumption, and the end-to-end workflows that connect incident creation through postmortem publication.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as follows: `PlatformAdmin`, `IncidentCommander`, and `ResponderUser`.

A `PlatformAdmin` is an operational administrator who provisions the static configuration of the platform — services, responders, schedules, shifts, policies, tiers, and maintenance windows — and who drives the test clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for capturing the actor, but it does not compare it to any entity's `id`.

An `IncidentCommander` coordinates live incidents: triggering them, manually escalating them, opening and closing war rooms, and authoring postmortems and action items. When `X-User-Role` is `IncidentCommander`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as the `author_id` written onto a war-room message at post time — but does not compare it to any entity's `id`.

A `ResponderUser` is an on-call engineer acting as themselves. When `X-User-Role` is `ResponderUser`, `X-User-ID` is the `id` of the acting `Responder`; ownership checks on any resource that references a `Responder` compare the resource's foreign-key field to `X-User-ID`. Concretely, acknowledging an incident verifies that a paging attempt for this responder exists, and starting or completing an action item verifies that the item's `owner_responder_id` equals `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Every resource also records a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, stamped when the resource is first created.

Most resources additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version` that begins at 1 and increments by exactly 1 on every mutation that changes the resource. Two resource kinds are append-only event logs and therefore deliberately omit these two fields: a paging attempt and a war-room message each carry only `id` and `created_at` — they have no `updated_at` and no `version`, because once written they are never mutated.

All datetime fields exchanged through the API — including `starts_at`, `ends_at`, `triggered_at`, `acknowledged_at`, `resolved_at`, `ack_deadline_at`, and `resolve_deadline_at` — use the same ISO 8601 UTC representation. SLA deadlines are stamped to whole seconds (that is, with `.000` in the fractional position).

### 2.5. The Logical Clock

Because SLA timers, on-call shift coverage, and maintenance-window activation all depend on "now," the platform reads time from a server-controlled logical clock rather than wall-clock time directly. An administrator-only test-driving capability sets this clock to a supplied instant via the `to_iso8601` field; once set, every subsequent timestamp the server stamps (`triggered_at`, `acknowledged_at`, `resolved_at`) and every coverage or window check uses that value. The capability echoes back the resulting clock as `current_utc`.

### 2.6. Concurrency Control and Versioning

Most mutations are unconditional: the server applies them and increments the resource's `version`. One operation, however, is guarded by optimistic concurrency control (OCC) to protect against advancing the escalation ladder from a stale view of an incident. A manual escalation request must carry `expected_incident_version`, a non-optional field whose value is the client's last observed `version` of the target incident. If that value does not equal the incident's current `version` at the time the request is processed — for instance because the system already advanced the ladder, created the next tier's paging attempts, and bumped the version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no tier is advanced and no page is sent. Endpoints other than manual escalation do not take a version field and are not subject to this check.

### 2.7. Nested Resource Retrieval and Referential Integrity

Several read endpoints are nested or filtered so that children can be retrieved relative to a parent — for example, listing the incidents of a service, the page attempts of an incident, or the action items of a postmortem. Path identifiers are validated left to right: the parent identifier in the path is resolved first, and only then are the child rows that reference it returned. When any resource identifier in a path, or any foreign key referenced in a request body, fails to resolve to an existing row, the request is rejected with the corresponding not-found error — `ERR_SERVICE_NOT_FOUND`, `ERR_RESPONDER_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_WAR_ROOM_NOT_FOUND`, `ERR_POSTMORTEM_NOT_FOUND`, `ERR_ACTION_ITEM_NOT_FOUND`, or `ERR_WINDOW_NOT_FOUND` (all HTTP 404), according to which entity failed to resolve.

### 2.8. Validation Ordering

When several checks apply to a single request, they are evaluated in a fixed priority order so that the most fundamental failures surface first and are never masked by a later check. The order is: (1) user-context headers must be present and the role recognized, else `ERR_MISSING_OR_INVALID_USER_CONTEXT`; (2) the acting role must be permitted for the operation, else `ERR_FORBIDDEN_ROLE`; (3) every path identifier and every body foreign key must resolve, else the appropriate not-found error; (4) required body fields must be present, well-typed, with valid enum members and in-range numerics, else `ERR_INVALID_REQUEST` (HTTP 422); (5) interval fields must be well-formed, else `ERR_INVALID_INTERVAL` (HTTP 422); (6) the target resource must be in the correct state for the requested transition, else the relevant state error (HTTP 409); (7) cross-entity state dependencies must hold (HTTP 409); (8) safety/ownership checks must pass (HTTP 403); and (9) and beyond, the domain-specific business constraints described in Section 3. In short: authentication, then authorization, then existence, then request shape, then interval well-formedness, then state, then cross-entity dependency, then ownership, then domain rules.

### 2.9. Precision and Rounding

All budget figures are tracked in whole integer minutes. Per-incident downtime is rounded up to a whole minute (ceiling) *before* any summation; the platform never sums seconds first and rounds afterward. Where a calculation multiplies a base SLA figure by a pressure factor, the result is rounded up to a whole minute (ceiling) after the multiplication. The warning threshold against a service's budget is also computed with a ceiling. Interval comparisons for shift overlap and window spacing are performed at second-level resolution.

### 2.10. State Mutation, Cascades, and Reconciliation

Several operations mutate more than one resource. When an operation changes a resource's state or computed fields, that resource's `updated_at` is refreshed and its `version` is incremented. Cascades propagate this: resolving an incident recomputes its parent service's consumed and remaining budget and re-derives the service's budget posture, each of which is an independent mutation of the service. Activating a maintenance window suppresses the affected service's still-triggered incidents, mutating each of them. The platform may also transition resources on its own — suppressing incidents, halting escalation — without an explicit client request against that specific resource. Each such reconciliation independently updates the affected resource's `updated_at` and `version`. The detailed cascade chains are specified in Section 3.

## 3. Business Logic & Workflows

### 3.1. Provisioning the On-Call Foundation

Before any incident can be paged, a `PlatformAdmin` builds out the static topology. A monitored service is created with a human-readable `name`, an importance `tier` — one of `TIER_1`, `TIER_2`, or `TIER_3`, defaulting to `TIER_2` when omitted — and an `error_budget_minutes` allowance, which is the total downtime in minutes the service may accumulate over an evaluation window and which must be strictly greater than zero. On creation, a service starts with `budget_status` of `HEALTHY`, `error_budget_consumed_minutes` of zero, and `error_budget_remaining_minutes` equal to the full `error_budget_minutes`. The tier carries weight far beyond labeling: a `TIER_1` service runs on a business-hours SLA clock, while `TIER_2` and `TIER_3` services run on a 24/7 calendar clock, as detailed in Section 3.5.

Responders are the humans who get paged. Each `Responder` is created with a `full_name` and an `email`, the latter serving as the always-available email channel address and required to be unique across all responders. Three optional contact fields define additional channels: `sms_number`, `voice_number`, and `push_token`. A null value in any of these disables that channel for the responder, so a responder with no `sms_number` is never paged by SMS.

On-call coverage is expressed through rotations and shifts. An `OnCallSchedule` is a named rotation tied to a service through `service_id`, with an advisory `handoff_interval_hours` describing the nominal rotation length, defaulting to 168 hours (one week) when omitted; the exact coverage intervals are pinned by the shifts themselves rather than by this advisory value. A `ScheduleShift` places a specific responder on call for a window of time: it carries a `schedule_id` naming the rotation it belongs to, a `responder_id` naming who is on call, and a `starts_at` / `ends_at` pair giving the half-open coverage interval `[starts_at, ends_at)`. The shift's `ends_at` must be strictly after its `starts_at`; otherwise the create is rejected with `ERR_INVALID_INTERVAL`. Shift coverage and overlap rules are described in Section 3.6.

Escalation behavior is configured per service. An `EscalationPolicy` is created against a service through `service_id` and names how many times the tier ladder repeats after all tiers have been tried, via `repeat_rounds`, which must be zero or greater and defaults to 1. Each rung of the ladder is an `EscalationTier` belonging to a policy through `policy_id`. A tier names the rotation it pages through `schedule_id`, a one-based ladder position `tier_level` that must be at least 1 and must be unique within its policy (a duplicate is rejected with `ERR_DUPLICATE_TIER_LEVEL`), and a `delay_minutes` value — the number of minutes after the previous tier with no acknowledgement before this tier would be paged — which must be zero or greater.

### 3.2. Triggering an Incident and the First Page

An incident is opened by an `IncidentCommander` or a `PlatformAdmin`. The trigger payload names the affected service via `service_id`, the escalation policy to apply via `policy_id`, a short `title`, and a `severity` that is one of `SEV1`, `SEV2`, `SEV3`, or `SEV4`. At creation the incident enters its initial state of `TRIGGERED` on the lifecycle dimension and `PENDING` on the escalation dimension, with `current_tier_level` of 0 (no tier paged yet). The server stamps `triggered_at` from the logical clock; this is the SLA baseline. The fields `acknowledged_at` and `resolved_at` are null until those events occur, and `counts_against_budget` defaults to true.

Immediately at trigger time the server computes the two SLA deadlines — `ack_deadline_at` and `resolve_deadline_at` — by the rules in Section 3.5, and sets `ack_sla_breached` to false initially. The acknowledgement deadline is derived from an *effective* ack-minutes figure that already folds in any budget pressure on the service (Section 3.5), whereas the resolve deadline uses the base resolve SLA for the severity.

What happens next depends on whether the service is under maintenance. If an `ACTIVE` maintenance window currently covers the service — that is, a window on the incident's `service_id` whose closed interval includes the current clock — the incident is born suppressed: `lifecycle_status` moves directly to `SUPPRESSED`, `counts_against_budget` is set to false, `escalation_status` is set to `EXHAUSTED`, and no page is sent and no paging attempt is recorded. Otherwise the system fires the first page automatically: `escalation_status` advances to `ESCALATING`, `current_tier_level` advances to tier 1, and one paging attempt is created per enabled channel of the responder selected for tier 1, exactly as described in Sections 3.3 and 3.4. If the policy has no tiers, or if tier 1's schedule has no shift covering the current clock, the trigger fails the reachable-target check with `ERR_NO_ESCALATION_TARGET` (HTTP 409).

### 3.3. Selecting the On-Call Target and the Paging Fan-Out

When the ladder pages a tier, the system must first decide *who* to page, then *how* to reach them. The target is selected from the rotation named by the tier's `schedule_id`. The candidate set is every shift on that schedule whose half-open interval covers the current clock — that is, whose `starts_at` is at or before now and whose `ends_at` is strictly after now. Candidates are ranked by `starts_at` ascending, with ties broken by `created_at` ascending; the resource `id` is never used as a tie-break. The selected target is the first candidate — the covering shift with the earliest start — and that shift's `responder_id` is the responder who will be paged. If the candidate set is empty (nobody is currently covering the tier's schedule), the system raises `ERR_NO_ESCALATION_TARGET`: no paging attempt is created and the escalation status stays at its prior value.

Once a target responder is chosen, the fan-out creates exactly one paging attempt per *enabled* channel of that responder, in a fixed channel-priority order: voice first when a `voice_number` is present, then SMS when an `sms_number` is present, then push when a `push_token` is present, and finally email, which is always present and always paged. The number of attempts produced by a single paging step therefore ranges from one (email only) to four (all channels enabled). Each `PageAttempt` records the `incident_id` it belongs to, the `responder_id` that was paged, the `tier_level` that produced it (the incident's `current_tier_level` at that step), the `channel` used — one of `SMS`, `VOICE`, `PUSH`, or `EMAIL` — and the `round_index`, a zero-based counter of how many times the ladder has wrapped around. Paging attempts are an append-only log: each carries only its `id` and `created_at`.

### 3.4. Climbing and Wrapping the Escalation Ladder

The escalation dimension is cyclic. The automatic first page at trigger time moves an incident from `PENDING` to `ESCALATING` and pages tier 1. From `ESCALATING`, an `IncidentCommander` can manually advance the ladder one rung at a time. A manual escalation may proceed only while the incident's `lifecycle_status` is still `TRIGGERED` — an incident that has already been acknowledged does not escalate. Each manual escalation must carry `expected_incident_version` equal to the incident's current `version`; if it does not match (because the ladder already advanced and bumped the version), the request is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in Section 2.6.

When a manual escalation succeeds, `current_tier_level` advances to the next tier, and when the ladder reaches past the highest configured tier it wraps to tier 1 again and the `round_index` advances — but only while repeat rounds remain within the policy's `repeat_rounds` budget. The new tier's responder is selected and paged through the same fan-out described in Section 3.3, and the incident's `version` is incremented by 1. The escalation status remains `ESCALATING` as long as there is a further tier or round to page. When no next tier remains within the configured repeat rounds, the escalation transitions from `ESCALATING` to `EXHAUSTED` and paging halts: no further paging attempts are created. The same reachable-target rule applies on every manual escalation step — if the next tier's schedule has no covering shift or the policy has no tiers, the step fails with `ERR_NO_ESCALATION_TARGET`.

The escalation dimension is independent of the lifecycle dimension. An incident can be `ACKNOWLEDGED` while its escalation status is `EXHAUSTED`, or `ESCALATING` while its lifecycle is still `TRIGGERED`. Two events drive the escalation status to `EXHAUSTED` from the system side, independent of running out of tiers: acknowledgement and suppression both halt the ladder, as described in Sections 3.7 and 3.8.

### 3.5. SLA Deadlines, Effective Tightening, and the Two Budget Accountings

**Base SLA windows.** Each severity carries a base acknowledgement window and a base resolve window in minutes. The acknowledgement windows are 15 minutes for `SEV1`, 30 minutes for `SEV2`, 120 minutes for `SEV3`, and 480 minutes for `SEV4`. The resolve windows are 240 minutes for `SEV1`, 480 minutes for `SEV2`, 1440 minutes (one day) for `SEV3`, and 4320 minutes (three days) for `SEV4`.

**Effective ack tightening.** Before the acknowledgement deadline is stamped, the base ack minutes for the severity are adjusted according to the service's budget posture, in this pinned order. Start from the base ack minutes for the severity. If the service's `budget_status` is `EXHAUSTED`, multiply the base by a pressure factor of 0.5 and round the product up to a whole minute; if instead the `budget_status` is `WARNING`, multiply the base by 0.75 and round up to a whole minute; otherwise (a `HEALTHY` service) the tightened figure equals the base. The effective ack minutes are then the larger of an absolute floor of 5 minutes and the smaller of the base and the tightened figure. In words: budget pressure can only tighten (shorten) the window, never below a 5-minute floor, and never above the base. This effective ack-minutes value — not the raw base — feeds the acknowledgement-deadline computation.

**Stamping the deadlines.** The deadlines are computed from `triggered_at` using one of two variants chosen by the service's tier. For a `TIER_2` or `TIER_3` service the *calendar* variant applies: the deadline is simply `triggered_at` plus the relevant minutes measured as 24/7 wall-clock minutes — the acknowledgement deadline is `triggered_at` plus the effective ack minutes, and the resolve deadline is `triggered_at` plus the base resolve minutes for the severity. For a `TIER_1` service the *business-hours* variant applies: only minutes that fall on Monday through Friday within the window from 09:00 (inclusive) up to 17:00 (exclusive) UTC count toward the deadline. The server walks forward from `triggered_at`, consuming only business minutes, until the required number of minutes (the effective ack minutes for the ack deadline, the base resolve minutes for the resolve deadline) has been consumed; the wall-clock instant reached at that point is the deadline. Minutes outside the business window are skipped, which pushes the wall-clock deadline later than the calendar variant would. Both deadlines are stamped to whole seconds.

**Breach flag.** The `ack_sla_breached` flag is true once the incident is acknowledged after its `ack_deadline_at`, or while it remains unacknowledged and the current clock has passed `ack_deadline_at`; otherwise it is false. It is recomputed at acknowledgement time, when it becomes true exactly when `acknowledged_at` is later than `ack_deadline_at`.

**Time-based consumed budget.** When budget is recomputed for a service (the resolve cascade in Section 3.7), the consumed figure is the *downtime-driven* total. For each incident on the service that is `RESOLVED` and whose `counts_against_budget` is true, the incident's `downtime_minutes` is the span from its `triggered_at` to its `resolved_at`, expressed in seconds, divided by 60, rounded up to a whole minute. The service's `error_budget_consumed_minutes` is the sum of those per-incident `downtime_minutes` over that set, with the per-incident ceiling applied to each incident *before* summing. Incidents whose `counts_against_budget` is false (the suppressed ones) contribute zero and are excluded from the set entirely. The service's `error_budget_remaining_minutes` is then the larger of zero and `error_budget_minutes` minus `error_budget_consumed_minutes`.

**Event-based cost (the second accounting).** The platform also exposes a structurally different way of spending the same budget pool, surfaced on the service budget-summary read alongside the time-based figure. The event-based cost charges each `RESOLVED`, budget-counting incident a *fixed* number of minutes by severity regardless of its actual downtime: 60 minutes for `SEV1`, 30 for `SEV2`, 10 for `SEV3`, and 5 for `SEV4`. The `event_cost_minutes` is the sum of those fixed per-incident costs over the same set of resolved, budget-counting incidents. Because it ignores actual downtime, this figure generally diverges from the time-based consumed number for the same incident set. The budget-summary read returns both side by side: `consumed_minutes` (the time-based total), `event_cost_minutes` (the event-based total), `remaining_minutes`, and `budget_status`.

**Budget posture.** A service's `budget_status` is re-derived from consumed versus budget with inclusive boundaries. Let consumed be `error_budget_consumed_minutes` and budget be `error_budget_minutes`. If consumed is greater than or equal to budget, the status is `EXHAUSTED`. Otherwise, if consumed is greater than or equal to the budget multiplied by 0.8 and rounded up to a whole minute, the status is `WARNING`. Otherwise the status is `HEALTHY`. The boundary is inclusive: consumed exactly equal to budget is `EXHAUSTED`, not `WARNING`.

### 3.6. Coverage Intervals: Shift Overlap and Window Spacing

Two interval rules use deliberately different semantics, and conflating them is a common error.

**Shift overlap** uses half-open intervals `[starts_at, ends_at)` with zero buffer. A new shift on a schedule is rejected when it overlaps any existing shift on the same `schedule_id`: an overlap exists exactly when the new shift's `starts_at` is strictly before the existing shift's `ends_at` and the existing shift's `starts_at` is strictly before the new shift's `ends_at`. Because the endpoints are half-open and there is no buffer, two back-to-back shifts where one's `starts_at` exactly equals the other's `ends_at` do *not* overlap and are allowed. A rejected overlap returns `ERR_SHIFT_OVERLAP` (HTTP 409).

**Window spacing** uses closed intervals `[starts_at, ends_at]` with a positive buffer. A maintenance window is created against a service through `service_id` with a `starts_at` / `ends_at` pair (its `ends_at` strictly after its `starts_at`, else `ERR_INVALID_INTERVAL`) and an optional free-text `reason`. For every existing non-`CANCELLED` window on the same service, the new window is rejected if it overlaps — its `starts_at` is at or before the existing window's `ends_at` and the existing window's `starts_at` is at or before the new window's `ends_at` — and, even when the two do not overlap, it is also rejected when the gap between them is less than a minimum spacing of 30 minutes. The gap is the larger of (the new window's `starts_at` minus the existing window's `ends_at`) and (the existing window's `starts_at` minus the new window's `ends_at`), compared at second-level resolution against 30 minutes' worth of seconds. In short, windows use closed endpoints and require at least a 30-minute separation, whereas shifts use half-open endpoints and permit back-to-back placement. A rejected spacing violation returns `ERR_WINDOW_OVERLAP` (HTTP 409). A new maintenance window begins in `SCHEDULED` status.

### 3.7. Acknowledging and Resolving an Incident

Acknowledgement is performed by a `ResponderUser`. It is permitted only while the incident's `lifecycle_status` is `TRIGGERED`; against any other lifecycle state it is rejected with `ERR_INCIDENT_NOT_TRIGGERED` (HTTP 409). Beyond the state check, the acting responder must actually have been paged for this incident: a paging attempt with `responder_id` equal to `X-User-ID` must exist, or the request is rejected with `ERR_RESPONDER_NOT_PAGED` (HTTP 403). On success the lifecycle moves to `ACKNOWLEDGED`, `acknowledged_at` is stamped from the clock, `ack_sla_breached` is recomputed (true exactly when `acknowledged_at` is later than `ack_deadline_at`), and — because acknowledgement halts the ladder — if the escalation status was `ESCALATING` it transitions to `EXHAUSTED` and `current_tier_level` is frozen at its current value.

Resolution is performed by a `ResponderUser` or an `IncidentCommander` and is permitted only while the lifecycle is `ACKNOWLEDGED`; otherwise it is rejected with `ERR_INCIDENT_NOT_ACKNOWLEDGED` (HTTP 409). On success the lifecycle moves to `RESOLVED`, `resolved_at` is stamped from the clock, and `downtime_minutes` is computed as the open-to-resolve span rounded up to a whole minute (since `counts_against_budget` is true for a normally resolved incident). Resolution then triggers a multi-hop cascade onto the parent service: `error_budget_consumed_minutes` is recomputed by the time-based aggregation of Section 3.5, `error_budget_remaining_minutes` is recomputed from it, and `budget_status` is re-derived — and if that re-derivation crosses the service to `EXHAUSTED`, that is a genuine third-hop state change on the service. Each hop refreshes the service's `updated_at` and increments its `version`. If an `OPEN` war room exists for the incident, it remains `OPEN`; it is closed separately (Section 3.9).

### 3.8. Maintenance Windows and Suppression

A maintenance window moves through a linear lifecycle driven by a `PlatformAdmin` (or by the clock crossing its bounds). A `SCHEDULED` window is activated only when its status is `SCHEDULED` (else `ERR_WINDOW_NOT_SCHEDULED`, HTTP 409) and the current clock falls within its closed interval; activation moves the `status` to `ACTIVE`. Activation cascades suppression: every incident on the window's service whose `lifecycle_status` is `TRIGGERED` is transitioned to `SUPPRESSED`, with `counts_against_budget` set to false and `escalation_status` driven to `EXHAUSTED` so paging halts — a second-hop change on each such incident caused by the window activation, each refreshing that incident's `updated_at` and `version`. An `ACTIVE` window is ended only from `ACTIVE` status (else `ERR_WINDOW_NOT_ACTIVE`, HTTP 409), moving `status` to `ENDED`. A `SCHEDULED` window may instead be cancelled, but only from `SCHEDULED` status (else `ERR_WINDOW_NOT_SCHEDULED`), moving `status` to `CANCELLED`. Suppression also occurs at incident-trigger time when a window is already `ACTIVE`, as described in Section 3.2; suppressed incidents never consume error budget because their `counts_against_budget` is false and they are excluded from every budget aggregation.

### 3.9. War Rooms and Coordination

An `IncidentCommander` opens a war room to coordinate a live incident. A `WarRoom` references its incident through `incident_id` and may carry an optional `bridge_url` video link; it begins in `OPEN` status. The relationship is one-to-one — at most one war room per incident — and a second attempt is rejected with `ERR_WAR_ROOM_EXISTS` (HTTP 409). Any of the three roles may post to an open war room. A `WarRoomMessage` carries the message `body`; at post time the server stamps the `author_role` from `X-User-Role` and, when present, the `author_id` from `X-User-ID`, and references the room through `war_room_id`. Messages are an append-only log carrying only `id` and `created_at`. A war room is closed by an `IncidentCommander`, permitted only while its `status` is `OPEN` (else `ERR_WAR_ROOM_NOT_OPEN`, HTTP 409) and only when the parent incident's `lifecycle_status` is `RESOLVED` (else `ERR_INCIDENT_NOT_RESOLVED`, HTTP 409); on success the `status` moves to `CLOSED`.

### 3.10. Postmortems and Action Items

After an incident is resolved, an `IncidentCommander` authors a postmortem. A `Postmortem` references the incident through `incident_id` and carries a `summary` root-cause narrative; it begins in `DRAFT` status with an `open_action_item_count` of zero. Creating a postmortem requires the referenced incident to be `RESOLVED`, else `ERR_INCIDENT_NOT_RESOLVED` (HTTP 409). The relationship is one-to-one — at most one postmortem per incident — and a duplicate is rejected with `ERR_POSTMORTEM_EXISTS` (HTTP 409).

Action items are remediation tasks hung off a postmortem. An `ActionItem` references its postmortem through `postmortem_id`, names an `owner_responder_id`, and carries a `description`; it begins in `OPEN` status. Creating an action item increments the parent postmortem's `open_action_item_count` by 1. The count reflects every child item whose status is `OPEN` or `IN_PROGRESS`. An action item walks a linear lifecycle with cancellation. The owning responder starts an item, moving it from `OPEN` to `IN_PROGRESS`; this is permitted only while the item's status is `OPEN` (else `ERR_ACTION_ITEM_NOT_OPEN`, HTTP 409) and only when the acting `ResponderUser`'s `X-User-ID` equals the item's `owner_responder_id` (else `ERR_NOT_ACTION_ITEM_OWNER`, HTTP 403); because both `OPEN` and `IN_PROGRESS` items are counted as open, the bubble-up recompute leaves `open_action_item_count` unchanged. The owner completes an item, moving it from `IN_PROGRESS` to `DONE`, permitted only while the status is `IN_PROGRESS` (else `ERR_ACTION_ITEM_NOT_IN_PROGRESS`, HTTP 409) and only by the owner (else `ERR_NOT_ACTION_ITEM_OWNER`); completion decrements the parent's `open_action_item_count` by 1. An `IncidentCommander` may cancel an item from either `OPEN` or `IN_PROGRESS`; cancellation is permitted only while the status is one of `OPEN` or `IN_PROGRESS` (else `ERR_ACTION_ITEM_TERMINAL`, HTTP 409) and moves the item to `CANCELLED`, decrementing the parent's `open_action_item_count` by 1 as a compensating adjustment that restores it toward the value before the item was created.

The postmortem itself is a branching workflow with a revision loop. From `DRAFT` an `IncidentCommander` submits it for review, moving it to `IN_REVIEW`, permitted only while the status is `DRAFT` (else `ERR_POSTMORTEM_NOT_DRAFT`, HTTP 409). From `IN_REVIEW` the commander may return it to `DRAFT` for further authoring — the revision loop — permitted only while the status is `IN_REVIEW` (else `ERR_POSTMORTEM_NOT_IN_REVIEW`, HTTP 409). Also from `IN_REVIEW` the commander may publish it, moving it to the terminal `PUBLISHED` status; publication is permitted only while the status is `IN_REVIEW` (else `ERR_POSTMORTEM_NOT_IN_REVIEW`) and only when `open_action_item_count` is zero — that is, every child action item is `DONE` or `CANCELLED` — else the publish is rejected with `ERR_OPEN_ACTION_ITEMS` (HTTP 409).

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2 and the authentication rules of Section 2.1. Creating a new resource returns HTTP 201; reads and state-changing modifications of an existing resource return HTTP 200. Request bodies, computed side effects, and cascades are not repeated here — reconstruct them from the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/services` | Create a monitored service | `PlatformAdmin` |
| GET | `/services` | List services (paginated) | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/services/{id}` | Get a service with computed budget fields | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/services/{id}/budget-summary` | Both budget accountings side by side | `PlatformAdmin`, `IncidentCommander` |
| GET | `/services/{id}/incidents` | List incidents for a service | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/services/{id}/maintenance-windows` | List maintenance windows for a service | `PlatformAdmin`, `IncidentCommander` |
| GET | `/services/{id}/escalation-policies` | List escalation policies for a service | `PlatformAdmin`, `IncidentCommander` |
| GET | `/services/{id}/on-call-schedules` | List on-call schedules for a service | `PlatformAdmin`, `IncidentCommander` |
| POST | `/responders` | Create a responder with contact channels | `PlatformAdmin` |
| GET | `/responders/{id}` | Get a responder | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| POST | `/on-call-schedules` | Create an on-call rotation for a service | `PlatformAdmin` |
| GET | `/on-call-schedules/{id}` | Get an on-call schedule | `PlatformAdmin`, `IncidentCommander` |
| POST | `/schedule-shifts` | Create an on-call shift (overlap-checked) | `PlatformAdmin` |
| GET | `/schedule-shifts` | List shifts; filter by `schedule_id`, `responder_id` | `PlatformAdmin`, `IncidentCommander` |
| GET | `/schedule-shifts/{id}` | Get a single on-call shift | `PlatformAdmin`, `IncidentCommander` |
| POST | `/escalation-policies` | Create an escalation policy for a service | `PlatformAdmin` |
| GET | `/escalation-policies/{id}` | Get an escalation policy | `PlatformAdmin`, `IncidentCommander` |
| GET | `/escalation-policies/{id}/incidents` | List incidents triggered under a policy | `PlatformAdmin`, `IncidentCommander` |
| POST | `/escalation-tiers` | Add a tier to a policy | `PlatformAdmin` |
| GET | `/escalation-tiers` | List tiers; filter by `policy_id`, `schedule_id` | `PlatformAdmin`, `IncidentCommander` |
| GET | `/escalation-tiers/{id}` | Get a single escalation tier | `PlatformAdmin`, `IncidentCommander` |
| POST | `/maintenance-windows` | Schedule a maintenance window for a service | `PlatformAdmin` |
| GET | `/maintenance-windows/{id}` | Get a maintenance window | `PlatformAdmin`, `IncidentCommander` |
| POST | `/maintenance-windows/{id}/activate` | Activate a window; suppresses triggered incidents | `PlatformAdmin` |
| POST | `/maintenance-windows/{id}/end` | End an active window | `PlatformAdmin` |
| POST | `/maintenance-windows/{id}/cancel` | Cancel a scheduled window | `PlatformAdmin` |
| POST | `/incidents` | Trigger an incident; fires the first page | `PlatformAdmin`, `IncidentCommander` |
| GET | `/incidents/{id}` | Get an incident | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| POST | `/incidents/{id}/acknowledge` | Acknowledge an incident; halts escalation | `ResponderUser` |
| POST | `/incidents/{id}/resolve` | Resolve an acknowledged incident | `ResponderUser`, `IncidentCommander` |
| POST | `/incidents/{id}/escalate` | Manually advance the ladder one tier (OCC-guarded) | `IncidentCommander` |
| GET | `/incidents/{id}/page-attempts` | List page attempts for an incident | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/page-attempts` | List page attempts; filter by `responder_id`, `incident_id` | `PlatformAdmin`, `IncidentCommander` |
| GET | `/page-attempts/{id}` | Get a single page attempt | `PlatformAdmin`, `IncidentCommander` |
| POST | `/war-rooms` | Open a war room for an incident | `IncidentCommander` |
| GET | `/war-rooms/{id}` | Get a war room | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/incidents/{id}/war-rooms` | List war rooms for an incident | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| POST | `/war-rooms/{id}/close` | Close a war room (requires incident resolved) | `IncidentCommander` |
| POST | `/war-rooms/{id}/messages` | Post a message to a war room | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/war-rooms/{id}/messages` | List war room messages | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| POST | `/postmortems` | Create a postmortem for a resolved incident | `IncidentCommander` |
| GET | `/postmortems/{id}` | Get a postmortem | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/incidents/{id}/postmortems` | List postmortems for an incident | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| POST | `/postmortems/{id}/submit` | Submit a draft postmortem for review | `IncidentCommander` |
| POST | `/postmortems/{id}/return` | Return an in-review postmortem to draft | `IncidentCommander` |
| POST | `/postmortems/{id}/publish` | Publish an in-review postmortem | `IncidentCommander` |
| POST | `/action-items` | Add an action item to a postmortem | `IncidentCommander` |
| GET | `/action-items/{id}` | Get an action item | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/postmortems/{id}/action-items` | List action items for a postmortem | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| GET | `/action-items` | List action items; filter by `owner_responder_id`, `postmortem_id` | `PlatformAdmin`, `IncidentCommander`, `ResponderUser` |
| POST | `/action-items/{id}/start` | Owner moves an action item to in-progress | `ResponderUser` |
| POST | `/action-items/{id}/complete` | Owner completes an action item | `ResponderUser` |
| POST | `/action-items/{id}/cancel` | Commander cancels an action item | `IncidentCommander` |
| POST | `/_clock/set_current_utc` | Test-driving: set the server clock | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SERVICE_NOT_FOUND` | 404 |
| `ERR_RESPONDER_NOT_FOUND` | 404 |
| `ERR_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_WAR_ROOM_NOT_FOUND` | 404 |
| `ERR_POSTMORTEM_NOT_FOUND` | 404 |
| `ERR_ACTION_ITEM_NOT_FOUND` | 404 |
| `ERR_WINDOW_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_INCIDENT_NOT_TRIGGERED` | 409 |
| `ERR_INCIDENT_NOT_ACKNOWLEDGED` | 409 |
| `ERR_INCIDENT_NOT_RESOLVED` | 409 |
| `ERR_NO_ESCALATION_TARGET` | 409 |
| `ERR_POSTMORTEM_NOT_DRAFT` | 409 |
| `ERR_POSTMORTEM_NOT_IN_REVIEW` | 409 |
| `ERR_OPEN_ACTION_ITEMS` | 409 |
| `ERR_ACTION_ITEM_NOT_OPEN` | 409 |
| `ERR_ACTION_ITEM_NOT_IN_PROGRESS` | 409 |
| `ERR_ACTION_ITEM_TERMINAL` | 409 |
| `ERR_NOT_ACTION_ITEM_OWNER` | 403 |
| `ERR_WINDOW_NOT_SCHEDULED` | 409 |
| `ERR_WINDOW_NOT_ACTIVE` | 409 |
| `ERR_WAR_ROOM_NOT_OPEN` | 409 |
| `ERR_RESPONDER_NOT_PAGED` | 403 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_POSTMORTEM_EXISTS` | 409 |
| `ERR_WAR_ROOM_EXISTS` | 409 |
| `ERR_DUPLICATE_TIER_LEVEL` | 409 |
| `ERR_STALE_VERSION` | 412 |
