# Robotics Competition API — Product Requirements Document

## 1. Introduction

Running a FIRST Robotics Competition event is an exercise in coordinating dozens of independent teams through a tightly choreographed season: registration and mentor background screening, the build window with its stop-build deadline, robot inspection, qualification match scheduling, alliance selection, playoff scoring, judging and awards, and finally the championship-qualification waterfall that decides which teams advance. Each of those stages has its own operators, its own segregation-of-duties rules, its own deadlines, and its own money flows, and a single missed precondition — a team without a cleared mentor, an unresolved critical violation, a screening package that was approved against a stale view of the person — can invalidate a weekend of work.

This document specifies the Robotics Competition API, a single REST surface mounted under `/frc-events` that orchestrates that whole lifecycle. It is written for the engineers who will build the implementation. It defines the access-control model, the global API contract (response envelope, pagination, optimistic concurrency, precision rules), the per-entity state machines and their side-effect cascades, the calculations that drive scoring, ranking, scheduling, seeding, awarding, posture, and reimbursement, and the full endpoint and error catalogue. Throughout, the guiding posture is **posture-driven gating**: a computed event-level posture (`OPEN`, `RESTRICTED`, `FROZEN`) gates most write operations, and nearly every actor action — a screening decision, a violation opened, a team disqualified — can ripple the posture and lock out downstream work until the ripple is resolved.

The intended readers are the implementation team, the test authors, and the operations staff who will run real events against this API. Business rules are stated precisely and anchored in concrete constants (kilograms, centimeters, cents, seconds, minutes, ranking points) so that a reader can reconstruct any acceptance test without needing any other document.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers. `X-User-ID` identifies the acting user; `X-User-Role` names the role under which they are acting. Both headers are mandatory on every endpoint, and a request missing either (or carrying a malformed value) is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are validated, the server checks that the named role is on the endpoint's permitted-role list; if not, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Both checks fire before any entity lookup, so a caller without the right role sees 403 rather than 404 even for a nonexistent resource.

The API recognises fourteen roles. Each is spelled exactly as the server expects to see it in the `X-User-Role` header: `EventDirector`, `RegistrationOfficer`, `ScreeningOfficer`, `TeamLead`, `ProcurementOfficer`, `Inspector`, `LeadInspector`, `HeadReferee`, `Scorekeeper`, `QueueManager`, `FieldResetCrew`, `JudgeAdvisor`, `Judge`, `TravelOfficer`.

The meaning of `X-User-ID` differs by role, because some roles are backed by a persisted `Person` row while others are not.

- When `X-User-Role` is `TeamLead`, `Inspector`, `LeadInspector`, `HeadReferee`, `Scorekeeper`, or `Judge`, `X-User-ID` is the `id` of the acting `Person`. Ownership checks on any resource that references a `Person` compare the resource's foreign-key field to `X-User-ID` — for example, an `Inspector` submitting a `RobotInspection` has their `X-User-ID` compared against the `RobotInspection.team_id`'s team to enforce the cannot-inspect-own-team rule, and a `Judge` completing an `InterviewSlot` has their `X-User-ID` compared against `InterviewSlot.judge_id`. The same entity-backed reading applies when the `TeamLead` confirms an `InterviewSlot` (compared to the slot's `team_id` through their own `Person.team_id`).
- When `X-User-Role` is `EventDirector`, `RegistrationOfficer`, `ScreeningOfficer`, `ProcurementOfficer`, `QueueManager`, `FieldResetCrew`, `JudgeAdvisor`, or `TravelOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `decided_by_role` context on a `ScreeningRecord`, or as audit metadata on a state transition) but does not compare it to any entity's `id`. Segregation-of-duties checks that involve an opaque role compare the opaque `X-User-ID` against the `opened_by_person_id` or `Person.id` stored on the target — a `ScreeningOfficer` approving their own submitted package trips the check because the `X-User-ID` matches the `Person.id` of the subject, even though the officer's identity is opaque.

Segregation of duties is a cross-cutting concern, not a per-endpoint decoration. The server rejects with `ERR_SEGREGATION_VIOLATION` (HTTP 403) any call in which the same human would be on both sides of a two-party control: a `ScreeningOfficer` approving or rejecting their own screening package, an `Inspector` submitting an inspection against their own team, a `HeadReferee` resolving a violation they themselves opened, a `HeadReferee` finalizing a match whose scores were entered by the same human acting as `Scorekeeper`, and a `ProcurementOfficer` approving a part order that the same human submitted as `TeamLead`. Each of these checks is enumerated again next to its owning workflow in §3.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and must be at most 100. `offset` defaults to 0 and must be a non-negative integer. List endpoints sort by `created_at` ascending unless otherwise stated. The response `meta` for list endpoints includes `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true if and only if `offset + limit` is less than `total_count`. A `limit` outside the permitted range, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every persisted entity carries `id` as a server-minted UUID with no type prefix. Entities annotated as common-fields entities also carry `created_at` (ISO 8601 UTC with three fractional digits, set at creation, never mutated thereafter), `updated_at` (same format, refreshed on every mutation), and `version` (integer starting at 1, incremented by exactly 1 on every write that mutates the entity). The one exception in this domain is `MatchScoreBreakdown`, which carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and it is never mutated after creation.

Three endpoints participate in optimistic concurrency control against a parent entity's `version`, and each names the OCC field explicitly in its request body. Approving a screening record requires `expected_person_version` matching the current `Person.version`; if the person's version has advanced since the caller last observed it, the call is rejected with `ERR_STALE_VERSION` (HTTP 412). Submitting an alliance pick requires `expected_round_version` matching the current `AllianceSelectionRound.version`; a stale round view — for example, one whose `current_captain_team_id` no longer reflects the latest pick — is likewise rejected with `ERR_STALE_VERSION`. Starting matches requires `expected_event_version` matching the current `FrcEvent.version`; this guards against a posture recomputation landing between the director's last read and the start-matches call. Endpoints not listed above do not take an OCC field. The check is purely a stale-version rejection; it does not depend on whether any other request is in flight at the same instant.

### 2.5. Numeric Precision, Currency, and Physical Constants

Money is always carried in integer cents — `cost_cents`, `unit_cost_cents`, `order_total_cents`, `reimbursed_cents` — and never as a fractional dollar amount. Ranking aggregates (`ranking_score`, `ranking_tie_break`) are carried to four decimal places and are rounded half-up at the final division step. Match scores, ranking points, and field-reset durations are integers; no fractional points or seconds are admitted.

Two physical limits are baked into the robot-inspection workflow and surfaced as named validation rules. `MAX_ROBOT_WEIGHT_KG` is 56.7 kilograms — a `RobotInspection` whose `weight_kg` is greater than 56.7 cannot be passed. `MAX_FRAME_PERIMETER_CM` is 304 centimeters — a `RobotInspection` whose `frame_perimeter_cm` is greater than 304 cannot be passed. Bumpers are a boolean: a pass requires `bumper_compliant` to be true. The build season calendar is also a hard constant: the stop-build deadline is whatever `scheduled_at` was recorded on the `STOP_BUILD` milestone, and part-order submission at any later instant is rejected with `ERR_STOP_BUILD_PASSED`.

Screening validity windows are expressed in days. When a `Person` is cleared, `screening_expires_at` is set to the clearance instant plus 180 days for `MENTOR` and `JUDGE`, and plus 90 days for `VOLUNTEER`. A `STUDENT` does not require screening, so `screening_expires_at` is null for them. The field-reset minimum interval is `FIELD_RESET_MIN_SECONDS` = 300 seconds (five minutes); no two consecutive matches on the same field may be scheduled closer than this. The qualification schedule is parameterised by `MIN_TEAMS_FOR_MATCHES` = 6 and `ROUNDS_PER_TEAM` = 8. Alliance selection seats `ALLIANCE_COUNT` = 8 captains, and a team must have at least `MIN_MATCHES_FOR_SEEDING` = 1 finalized qualification match to be eligible for captain seeding.

### 2.6. Event Posture as a Cross-Cutting Gate

A `FrcEvent` carries a derived `posture` field with three values: `OPEN`, `RESTRICTED`, `FROZEN`. Posture is recomputed by the `event_posture` calculation whenever any of its inputs change — a screening decision, a violation opened, resolved, or escalated, a team disqualified, or a screening expiry cascade. The rule is: count the event's unresolved `CRITICAL` violations (`critical_open`) and count its confirmed teams that have no cleared mentor (`uncleared_mentors`). If `critical_open` is at least `CRITICAL_FREEZE_THRESHOLD` = 3, posture becomes `FROZEN`. Otherwise, if `critical_open` is greater than zero or `uncleared_mentors` is greater than zero, posture becomes `RESTRICTED`. Otherwise posture is `OPEN`.

Posture gates writes throughout the API. Any write attempted while posture is `FROZEN` is rejected with `ERR_EVENT_FROZEN` (HTTP 409). Operations that additionally require `OPEN` posture — locking registration, opening build season, confirming a team, starting matches — fail with `ERR_EVENT_FROZEN` when posture is `RESTRICTED` as well as when it is `FROZEN`. The posture check fires after authentication and existence, but before the entity's own state-machine checks.

### 2.7. Validation Priority Ordering

Every endpoint runs its checks in a fixed priority order so that callers see a deterministic error when several rules are simultaneously violated. The order is:

1. Header presence and shape (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Path-parameter existence — every id in the path must resolve to a real entity nested under its parent. The specific error varies by which segment failed: `ERR_EVENT_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_PERSON_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_ALLIANCE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SLOT_NOT_FOUND` (used for both `InterviewSlot` and `QueueSlot`), `ERR_BOOKING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_RESET_LOG_NOT_FOUND`.
4. Event-level status (`ERR_EVENT_WRONG_STATUS`) — the `FrcEvent` must be in the status the operation expects.
5. Posture (`ERR_EVENT_FROZEN`) — no write while `FROZEN`; some operations additionally require `OPEN`.
6. Entity state (`ERR_INVALID_STATE`) — the target entity must be in the `from` state the transition requires; if it is already in a terminal state, the more specific `ERR_ALREADY_TERMINAL` is used instead.
7. Segregation of duties (`ERR_SEGREGATION_VIOLATION`).
8. Screening-record freshness (`ERR_RECORD_NOT_PENDING`).
9. Inspector clearance (`ERR_INSPECTOR_NOT_CLEARED`) and self-inspection (`ERR_INSPECTOR_SELF`).
10. Mentor clearance before roster submission (`ERR_MENTOR_NOT_CLEARED`).
11. Event capacity (`ERR_EVENT_FULL`).
12. Stop-build deadline (`ERR_STOP_BUILD_PASSED`).
13. Field reset before take-field (`ERR_FIELD_NOT_RESET`).
14. Judge double-booking (`ERR_JUDGE_DOUBLE_BOOKED`).
15. Field interval between consecutive matches (`ERR_FIELD_INTERVAL_VIOLATION`).
16. Alliance pick eligibility (`ERR_PICK_INELIGIBLE`).
17. Alliance pick turn order (`ERR_OUT_OF_TURN`).
18. Build-season budget cap (`ERR_BUDGET_EXCEEDED`).
19. Reimbursement mode cap (`ERR_REIMBURSEMENT_CAP_EXCEEDED`).
20. Team-number uniqueness (`ERR_DUPLICATE_TEAM_NUMBER`).
21. Match-number uniqueness (`ERR_DUPLICATE_MATCH_NUMBER`).
22. Stale OCC version (`ERR_STALE_VERSION`).

Lower numbers win. For example, a `ScreeningOfficer` calling approve on a person whose `X-User-Role` header is malformed gets `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, never a 404, even if the person does not exist. A `TeamLead` calling confirm against a team that does not exist gets `ERR_TEAM_NOT_FOUND`, not `ERR_EVENT_FROZEN`, even when the event is frozen.

### 2.8. Nested Resource Resolution and Hierarchy

The URL hierarchy mirrors the entity hierarchy. An `FrcEvent` is the root. Beneath it sit `Team`, `Person`, `BuildSeasonMilestone`, `Match`, `Alliance`, `AllianceSelectionRound`, and `Award`. Beneath a `Team` sit `PartOrder`, `RobotInspection`, `ComplianceViolation`, and `TravelBooking`. Beneath a `Person` sit `ScreeningRecord`. Beneath a `Match` sit `MatchScoreBreakdown`, `QueueSlot`, and `FieldResetLog`. Beneath an `Award` sit `InterviewSlot`. Path parameters are validated left to right, so a request for a `PartOrder` under a nonexistent `Team` returns `ERR_TEAM_NOT_FOUND`, never `ERR_ORDER_NOT_FOUND`. Once an entity is resolved, it is implicitly scoped to its ancestors — a `PartOrder` reachable through `/frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}` belongs to that team and that event.

For foreign-key reverse-reachability, the API also exposes flat list and get routes — `/frc-events/teams`, `/frc-events/persons`, `/frc-events/screening-records`, `/frc-events/milestones-flat`, `/frc-events/matches-flat`, `/frc-events/part-orders`, `/frc-events/robot-inspections`, `/frc-events/violations`, `/frc-events/alliances-flat`, `/frc-events/alliance-selection-rounds-flat`, `/frc-events/score-breakdowns`, `/frc-events/queue-slots`, `/frc-events/field-reset-logs`, `/frc-events/awards-flat`, `/frc-events/interview-slots`, `/frc-events/travel-bookings`, plus their singular get-by-id forms — each accepting the foreign key as a query parameter so a caller can navigate from any aggregate back to its members without knowing the parent id in advance.

Path-parameter names are stable across the API and use camelCase. The event segment is `eventId`, the team segment is `teamId`, the person segment is `personId`, the screening-record segment is `recordId`, the milestone segment is `milestoneId`, the part-order segment is `orderId`, the robot-inspection segment is `inspectionId`, the violation segment is `violationId`, the match segment is `matchId`, the score-breakdown segment is `breakdownId`, the queue-slot and interview-slot segments are both `slotId`, the field-reset-log segment is `logId`, the alliance segment is `allianceId`, the alliance-selection-round segment is `roundId`, the award segment is `awardId`, and the travel-booking segment is `bookingId`.

### 2.9. Logical Clock and Test-Driving

The server maintains a logical clock (`current_utc`) used by every temporal rule — screening expiry, the stop-build deadline, the no-show detection window on interview slots. The clock defaults to `2026-05-01T00:00:00Z` if it has never been set. An admin-only test-driving capability advances the clock to a supplied `to_iso8601` instant; this is an `EventDirector`-only operation. Advancing the clock triggers the `screening_expiry` calculation, which transitions every `Person` whose `screening_status` is `CLEARED` and whose `screening_expires_at` has been reached or passed into `EXPIRED`. That expiry, in turn, can leave a confirmed team without a cleared mentor, which triggers a posture recomputation — so a single clock advance can flip an event from `OPEN` to `RESTRICTED`.

### 2.10. Computed and Aggregated Fields

Several entity fields are computed by the server and never accepted as input. On `FrcEvent`, `registered_team_count` is the count of linked `Team` rows whose `registration_status` is `CONFIRMED`; `cleared_mentor_count` is the count of `Person` rows linked to a confirmed team of this event whose `role_kind` is `MENTOR` and whose `screening_status` is `CLEARED`; `outstanding_violation_count` is the count of `ComplianceViolation` rows (for teams of this event) whose `resolution_status` is anything other than `RESOLVED`. On `Team`, `ranking_score`, `ranking_tie_break`, `matches_played`, `is_alliance_captain`, and `qualified_for_championship` are all computed. On `PartOrder`, `submitted_at` is set on the `DRAFT → SUBMITTED` transition, and `order_total_cents` is the product of `quantity` and `unit_cost_cents`. On `Match`, `red_score`, `blue_score`, `red_ranking_points`, and `blue_ranking_points` are computed by the scoring pipeline. On `QueueSlot`, `arrived_at` is set on the `STAGED → AT_FIELD` transition. On `FieldResetLog`, `completed_at` and `actual_seconds` are set on the `IN_PROGRESS → COMPLETE` transition; `actual_seconds` is the difference in seconds between `completed_at` and `started_at`. On `InterviewSlot`, `score` is set on completion. On `TravelBooking`, `reimbursed_cents` is set on approval and reset to zero on denial, and its `reimbursement_status` walks `PENDING → APPROVED → PAID` or `PENDING → DENIED`. On `Person`, `screening_expires_at` is set on clearance and cleared implicitly on rejection. On `ScreeningRecord`, `decision` and `decided_by_role` are server-side fields.

Foreign-key fields name the parent they point at. `Team.event_id`, `PartOrder.team_id` and `PartOrder.event_id` (the latter denormalized from the team), `RobotInspection.team_id` and `RobotInspection.inspector_id`, `ComplianceViolation.team_id` and `ComplianceViolation.opened_by_person_id`, `Match.event_id`, `Match.red_alliance_id` and `Match.blue_alliance_id`, `MatchScoreBreakdown.match_id`, `QueueSlot.match_id` and `QueueSlot.team_id`, `FieldResetLog.match_id`, `Alliance.event_id`, `Alliance.captain_team_id`, `Alliance.pick1_team_id`, `Alliance.pick2_team_id`, `AllianceSelectionRound.event_id`, `AllianceSelectionRound.current_captain_team_id`, `AllianceSelectionRound.round_index` (1 for the first pick round, 2 for the snake-return second round), `Award.event_id` and `Award.winner_team_id`, `InterviewSlot.award_id`, `InterviewSlot.team_id`, `InterviewSlot.judge_id`, `TravelBooking.team_id`, `BuildSeasonMilestone.event_id`, and `ScreeningRecord.person_id` — all are server-set at creation or transition time and never accepted from the wire on update.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Event: From Setup to Registration

An `EventDirector` brings a new event into existence by supplying its identifying metadata: an `event_code` (unique across all events, e.g. `"PNW-2026"`), an `event_name` for display, the `season_year`, the `start_date` and `end_date` in ISO 8601 UTC, the venue's `team_capacity`, the nominal `match_cycle_minutes` per slot (which must be at least 4), the `field_count` (at least 1), and the number of `championship_slots` the event is authorised to grant. The new event is born in `SETUP` status with `posture` equal to `OPEN` and all three computed counters (`registered_team_count`, `cleared_mentor_count`, `outstanding_violation_count`) at zero. The server returns the freshly created event with HTTP 201.

Before registration can open, the director must schedule the build-season calendar. Each milestone is created with a `kind` drawn from `KICKOFF`, `STOP_BUILD`, `BAG_DAY`, `SHIP_DATE`, `UNBAG_WINDOW`, plus a `scheduled_at` instant and a `window_minutes` duration. `window_minutes` is meaningful only for `UNBAG_WINDOW`; for point-in-time milestones it is recorded as 0, and for `UNBAG_WINDOW` it must be greater than 0. Milestones are born in `SCHEDULED` status; they transition `SCHEDULED → ARMED` when the parent event enters build season, and `ARMED → PASSED` (or directly `SCHEDULED → PASSED`) when the director marks them passed. A milestone whose window is cancelled before it completes can land in `CANCELLED`, which is terminal.

Opening registration requires two things in priority order: at least one `KICKOFF` milestone exists in `SCHEDULED` status, and `team_capacity` is greater than zero. If the kickoff milestone is missing, the call is rejected with `ERR_MILESTONE_MISSING`. When the gate passes, the event transitions `SETUP → REGISTRATION_OPEN` and the `event_posture` calculation is run as a side effect — though in practice at this point no violations exist and no teams are confirmed, so posture remains `OPEN`.

### 3.2. Team Registration, Screening, and Confirmation

A `RegistrationOfficer` registers a team by providing a `team_number` (a positive integer, unique within the event) and a public `nickname`. A duplicate `team_number` is rejected with `ERR_DUPLICATE_TEAM_NUMBER` (HTTP 409). The new `Team` is born with `registration_status` equal to `PENDING_PAYMENT` and `robot_inspection_status` equal to `NOT_SUBMITTED`; it is linked to its parent event through `event_id`. The officer marks payment received to move the team `PENDING_PAYMENT → PAYMENT_CLEARED`; this is permitted only while the event is in `REGISTRATION_OPEN`, and any attempt at another event status is rejected with `ERR_EVENT_NOT_ACCEPTING`-style state rejection — concretely, the event-status check fires first under priority 4 and returns `ERR_EVENT_WRONG_STATUS`.

Once payment has cleared, the team's `TeamLead` assembles the roster. Roster submission moves the team `PAYMENT_CLEARED → ROSTER_SUBMITTED` and has two preconditions, both required: the team must have at least one linked `Person` with `role_kind` equal to `MENTOR` and `screening_status` equal to `CLEARED`, and the team must have at least one linked `Person` with `role_kind` equal to `STUDENT`. Failing the mentor check produces `ERR_MENTOR_NOT_CLEARED` (HTTP 422). A `TeamLead` (or a `RegistrationOfficer`) registers a person by providing `full_name`, `email` (which must satisfy RFC 5322 and is unique per event), `role_kind` (one of `MENTOR`, `VOLUNTEER`, `JUDGE`, `STUDENT`), and optionally `team_id` (null for event-level volunteers). A `Person` is born with `screening_status` equal to `PENDING`.

A `ScreeningOfficer` drives the screening pipeline. They submit a screening package by creating a `ScreeningRecord` against the person, providing `submission_channel` (`FIRST_YPP`, `VENDOR_API`, or `MANUAL_UPLOAD`), a `vendor_reference` string, and the `submitted_at` timestamp. Creating the record moves the person `PENDING → IN_REVIEW` and creates the record with `decision` equal to `PENDING`. This submission is permitted only while the event's `status` is `SETUP`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED`. Approval moves the person `IN_REVIEW → CLEARED`: the officer calls approve with `expected_person_version` matching the person's current `version` (an OCC rule — see §2.4), the server checks that the latest `ScreeningRecord.decision` is `PENDING` (otherwise `ERR_RECORD_NOT_PENDING`, HTTP 409), and that the officer is not the person themselves (otherwise `ERR_SEGREGATION_VIOLATION`, HTTP 403). On success the record's `decision` flips to `APPROVE`, `decided_by_role` records `ScreeningOfficer`, the person's `screening_expires_at` is set to the current instant plus 180 days for `MENTOR`/`JUDGE` or 90 days for `VOLUNTEER`, the event's `posture` is recomputed, and `cleared_mentor_count` is recomputed. Rejection works symmetrically: the officer calls reject (no OCC field is taken), the same `decision == PENDING` and segregation checks fire, the person transitions `IN_REVIEW → REJECTED`, posture is recomputed, and as a knock-on cascade — if the rejected person was a `MENTOR` and the linked team's `registration_status` was `ROSTER_SUBMITTED`, the team reverts to `PAYMENT_CLEARED`.

Confirmation is the final registration step. A `RegistrationOfficer` confirms a `ROSTER_SUBMITTED` team, which moves it `ROSTER_SUBMITTED → CONFIRMED`. Confirmation requires the event's `registered_team_count` to be strictly less than `team_capacity` (else `ERR_EVENT_FULL`, HTTP 409) and requires posture to be `OPEN` — under `RESTRICTED` or `FROZEN` the call is rejected with `ERR_EVENT_FROZEN`. On success, `registered_team_count` increments by 1 and `cleared_mentor_count` is recomputed.

Withdrawal is the team-initiated exit. From `PENDING_PAYMENT`, withdrawal has no preconditions and no side effects beyond the team's own state change. From `CONFIRMED`, withdrawal is permitted at any event status except `AWARDS` and `CLOSED` — withdrawal during those statuses is rejected under the event-status check. The side effects are layered: `registered_team_count` decrements by 1, every `QueueSlot` belonging to this team that is currently `STAGED` or `AT_FIELD` flips to `NO_SHOW`, and every `InterviewSlot` belonging to this team that is currently `PROPOSED` or `CONFIRMED` flips to `CANCELLED`.

Disqualification is the director-initiated exit and is heavier. A `CONFIRMED` team may be disqualified only when at least one `ComplianceViolation` exists against it with `severity` equal to `CRITICAL` and `resolution_status` not equal to `RESOLVED`; otherwise the call is rejected with `ERR_NO_GROUNDS` (HTTP 409). On success, `registered_team_count` decrements by 1, every `Match` row where the team appears and that is still in `SCHEDULED` status flips to `CANCELLED` (with a replay to be scheduled later), every `InterviewSlot` for the team flips to `CANCELLED`, and if the team was on any `Alliance` still in `FORMING` status — as `captain_team_id`, `pick1_team_id`, or `pick2_team_id` — those slots are cleared and the alliance remains in `FORMING`. Disqualification also feeds the `event_posture` recomputation.

When registration closes, the director locks it: `REGISTRATION_OPEN → REGISTRATION_LOCKED` requires posture `OPEN` (otherwise `ERR_EVENT_FROZEN`) and sweeps every team still in `PENDING_PAYMENT` or `PAYMENT_CLEARED` to `WITHDRAWN`, recomputing `registered_team_count` accordingly. The lock increments the event's `version` by 1.

### 3.3. Build Season and Parts Procurement

Opening build season moves the event `REGISTRATION_LOCKED → BUILD_SEASON`. Preconditions: posture must be `OPEN`, and `registered_team_count` must be at least 2 — a smaller field is rejected with `ERR_TOO_FEW_TEAMS` (HTTP 409). On success, the `KICKOFF` milestone flips to `ARMED`.

During build season, teams order parts against their build-season budget. A `TeamLead` creates a `PartOrder` by supplying `sku`, `quantity` (must be greater than 0), and `unit_cost_cents` (must be at least 0). The order is born in `DRAFT` status; the server immediately computes `order_total_cents` as the product of `quantity` and `unit_cost_cents`. Submission moves `DRAFT → SUBMITTED` and is gated on three things in priority order: the event must be in `BUILD_SEASON` (otherwise `ERR_NOT_BUILD_SEASON`, HTTP 409), the current logical clock must be at or before the `scheduled_at` of the `STOP_BUILD` milestone (otherwise `ERR_STOP_BUILD_PASSED`, HTTP 422), and the team must be `CONFIRMED`. On success, `submitted_at` is stamped with the current instant and `order_total_cents` is recomputed.

Procurement is segregated. A `ProcurementOfficer` approves a `SUBMITTED` order, which moves it `SUBMITTED → APPROVED` — but only if the officer is not the same human who submitted the order as `TeamLead`; if they are, the call is rejected with `ERR_SEGREGATION_VIOLATION`. Approval is also the gate where the team's build-season budget cap is enforced: the order's `order_total_cents`, when added to the team's already-approved spend, must not exceed the per-event budget cap, else `ERR_BUDGET_EXCEEDED` (HTTP 402). Rejection moves `SUBMITTED → REJECTED` with no additional preconditions. From `APPROVED`, the officer places the order with the vendor (`APPROVED → VENDOR_PLACED`), and the `TeamLead` confirms physical receipt (`VENDOR_PLACED → RECEIVED`). Cancellation is permitted from `DRAFT` and from `SUBMITTED`, both landing in `CANCELLED`. `RECEIVED`, `REJECTED`, and `CANCELLED` are terminal; mutating an order already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`.

### 3.4. Inspection and Robot Compliance

When the `STOP_BUILD` milestone has been marked `PASSED`, the director opens inspection: the event moves `BUILD_SEASON → INSPECTION`. A `STOP_BUILD` milestone in any other state causes rejection with `ERR_MILESTONE_NOT_PASSED` (HTTP 409).

An `Inspector` opens a robot inspection against a team by supplying `inspector_id` (the `Person.id` of the inspector), `weight_kg` (must be greater than 0), `frame_perimeter_cm`, and `bumper_compliant` (a boolean). The inspection is born in `DRAFT` status. Submission moves `DRAFT → SUBMITTED` and is gated on the event being in `INSPECTION`, on the inspector being a `Person` whose `role_kind` is `MENTOR` or `VOLUNTEER` and whose `screening_status` is `CLEARED` (otherwise `ERR_INSPECTOR_NOT_CLEARED`, HTTP 422), and on the inspector not belonging to the team being inspected — `Inspector.team_id` must differ from `RobotInspection.team_id` (otherwise `ERR_INSPECTOR_SELF`, HTTP 422).

A `LeadInspector` decides the outcome. Passing requires three physical checks to all hold: `weight_kg` at most 56.7 (else `ERR_ROBOT_OVERWEIGHT`), `frame_perimeter_cm` at most 304 (else `ERR_FRAME_TOO_LARGE`), and `bumper_compliant` equal to true (else `ERR_BUMPERS_NONCOMPLIANT`). On a pass, the inspection moves `SUBMITTED → PASSED`, the team's `robot_inspection_status` flips to `PASSED`, and any prior `RobotInspection` rows for the same team still in `SUBMITTED` are flipped to `SUPERSEDED`. On a fail, the inspection moves `SUBMITTED → FAILED`, the team's `robot_inspection_status` flips to `FAILED`, and the server creates a `ComplianceViolation` against the team with `source_kind` set to `INSPECTION`, `severity` set to `MAJOR`, and `resolution_status` set to `OPEN`, recomputing the event's `outstanding_violation_count`. The team's `robot_inspection_status` can also land in `WAIVED` through operational exception paths discussed in the inspection workflow.

Violations are the operational currency of compliance. Anyone authorised — `HeadReferee`, `Inspector`, `LeadInspector`, or `JudgeAdvisor` — can open a `ComplianceViolation` against a team by supplying `source_kind` (`INSPECTION`, `MATCH_REVIEW`, `FIELD_SAFETY`, or `JUDGE_REFERRAL`), `severity` (`MINOR`, `MAJOR`, or `CRITICAL`), free-text `description`, and `opened_by_person_id`. The violation is born in `OPEN` status; opening one recomputes both `outstanding_violation_count` and `posture`. The team's `TeamLead` acknowledges it (`OPEN → ACKED`) with no preconditions. A `HeadReferee` resolves it (`ACKED → RESOLVED`) — but only if they are not the person recorded as `opened_by_person_id`, else `ERR_SEGREGATION_VIOLATION`; resolution recomputes `outstanding_violation_count` and `posture`. A `HeadReferee` may also escalate an `OPEN` violation (`OPEN → ESCALATED`), but only when `severity` is `CRITICAL`; escalation recomputes `posture`. `RESOLVED` is the only terminal state.

### 3.5. Match Scheduling and the Qualification Run

Starting matches moves the event `INSPECTION → MATCHES_RUNNING`. This is an OCC-guarded call: the director must pass `expected_event_version` matching the event's current `version`; a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). Beyond OCC, three preconditions must all hold: every `CONFIRMED` team must have `robot_inspection_status` in {`PASSED`, `WAIVED`} (else `ERR_INSPECTION_INCOMPLETE`, HTTP 409), the count of unresolved `CRITICAL` violations must be zero, and posture must not be `FROZEN`. On success the `generate_match_schedule` calculation runs and produces the qualification slate.

The schedule generator operates as follows. It collects every `Team` of the event whose `registration_status` is `CONFIRMED` and whose `robot_inspection_status` is `PASSED` or `WAIVED`, then sorts them deterministically by `team_number` ascending with `created_at` ascending as the tie-breaker — never by `id`. If fewer than 6 teams qualify, the run aborts with `ERR_TOO_FEW_TEAMS`. With `N` teams and `ROUNDS_PER_TEAM` equal to 8, the generator produces a round-robin slate in which the total number of rounds is the ceiling of `N` divided by 6, multiplied by 8. Each match carries 6 distinct teams (3 on the red alliance, 3 on the blue); no team plays twice in the same round. Matches are slotted across fields `1` through `field_count` in round-robin fashion, and any two consecutive matches on the same field must be separated by at least `FIELD_RESET_MIN_SECONDS` = 300 seconds of `scheduled_at` time — a violation of this interval is rejected with `ERR_FIELD_INTERVAL_VIOLATION` (HTTP 422). Generated matches are born in `SCHEDULED` status. The event's `version` increments by 1 as part of the start-matches write.

Manual match creation is also available for playoffs and replays. A `EventDirector` or `Scorekeeper` creates a `Match` by supplying `match_number` (at least 1, unique within the pair of `event_id` and `series` — a duplicate is rejected with `ERR_DUPLICATE_MATCH_NUMBER`), `series` (`QUALIFICATION` or `PLAYOFF`), `scheduled_at`, `field_index` (at most the event's `field_count`), `red_alliance_id`, and `blue_alliance_id`. The new match is born in `SCHEDULED`.

A match's lifecycle is `SCHEDULED → QUEUED → ON_FIELD → SCORED → FINALIZED`, with `REPLAYED` and `CANCELLED` as the alternatives. Queueing requires the event to be in `MATCHES_RUNNING` or `ALLIANCE_SELECTION`, and requires all 6 `QueueSlot` rows for the match to exist — otherwise `ERR_INCOMPLETE_QUEUE` (HTTP 409). On queueing, every `QueueSlot` flips to `STAGED`. A `QueueManager` creates each `QueueSlot` by supplying `team_id` and `position` (`RED_1`, `RED_2`, `RED_3`, `BLUE_1`, `BLUE_2`, `BLUE_3`); slots are born in `STAGED`. Marking a team at-field moves that slot `STAGED → AT_FIELD`, requires the match to be in `QUEUED` (else `ERR_MATCH_NOT_QUEUED`), and stamps `arrived_at` with the current instant. Taking the field moves the match `QUEUED → ON_FIELD`: every slot must already be `AT_FIELD` (else `ERR_TEAM_NOT_AT_FIELD`), and the prior `FieldResetLog` for the same `field_index` must be `COMPLETE` (or nonexistent — the first match of the day has no prior reset), else `ERR_FIELD_NOT_RESET`. On take-field, every slot flips to `ON_FIELD`.

Scoring is the compute-heavy step. A `Scorekeeper` attaches two `MatchScoreBreakdown` rows to the match — one with `alliance_color` set to `RED`, one with `BLUE` — each supplying `auto_points`, `teleop_points`, `endgame_points`, `foul_points_awarded`, `tech_foul_count`, and `card_issued` (`NONE`, `YELLOW`, or `RED`). All four point fields must be non-negative. Scoring the match moves `ON_FIELD → SCORED`; it requires both breakdowns to be attached (else `ERR_SCORE_BREAKDOWN_MISSING`). On the transition, `score_match` runs in its **provisional** variant and `red_score` and `blue_score` are written; for a `QUALIFICATION` match the `ranking_points` calculation also runs; every `QueueSlot` flips to `RELEASED`; and a `FieldResetLog` is created against the match with `status` equal to `IN_PROGRESS` and `field_index` copied from the match.

The `score_match` formula in its provisional variant computes, for each alliance color, a base of `auto_points + teleop_points + endgame_points`, adds `foul_points_awarded`, and subtracts the product of `tech_foul_count` and 5. Card penalties are not applied at this stage. The gross is floored at zero, so a provisional alliance score is never negative.

Finalization is performed by a `HeadReferee`, and the same human may not both score and finalize — the referee's `X-User-ID` is compared against the `Person.id` of the scorekeeper who performed the score transition, and a match is rejected with `ERR_SEGREGATION_VIOLATION`. On `SCORED → FINALIZED`, `score_match` re-runs in its **final** variant: the provisional formula is extended by subtracting a card penalty — 0 if `card_issued` is `NONE`, 10 if `YELLOW`, 30 if `RED`. A match that provisional-scored at 120 and was then yellow-carded finalizes at 110. The final score is again floored at zero. After both `red_score` and `blue_score` are recomputed, `team_ranking_score` runs for each of the six participating teams: `matches_played` increments by 1, and `ranking_score` and `ranking_tie_break` are recomputed. Finalization also requires that the `FieldResetLog` for this match be transitioned to `COMPLETE` before the next match on the same field can take the field — that constraint is enforced on the take-field side via `ERR_FIELD_NOT_RESET`.

The `ranking_points` calculation runs at score time for `QUALIFICATION` matches only. For each alliance color, the ranking points earned are: 2 if the alliance's score is strictly greater than the opponent's, 1 if equal, 0 otherwise. Bonus points are added when the alliance's breakdown exceeds fixed thresholds — strictly greater than 25 `auto_points` earns 1 bonus ranking point, and strictly greater than 20 `endgame_points` earns another 1 bonus ranking point. The bonuses use strict greater-than, not greater-than-or-equal; exactly 25 auto points earns no bonus. The ranking points earned are written to the match as `red_ranking_points` and `blue_ranking_points`.

The `team_ranking_score` calculation runs at finalize time and is the aggregation step that produces each team's standing. For each team on the just-finalized match, it collects every `QUALIFICATION` match in `FINALIZED` status on which the team appears (either alliance), sorts them by `match_number` ascending with `created_at` ascending as the tie-break, and accumulates three quantities: the sum of the team's-side ranking points (`rp_sum`), the sum of the team's-side `auto_points + endgame_points` from the corresponding breakdown (`tie_break_sum`), and the count of those matches (`n`). The team's `ranking_score` is then `rp_sum` divided by `n`, rounded half-up to 4 decimal places; `ranking_tie_break` is `tie_break_sum` divided by `n`, also rounded half-up to 4 decimal places; `matches_played` is `n`. Because the running set is rebuilt from scratch at each finalize, reversing a match out (see below) automatically excludes it from the next recompute — this is the pinned **chronological** variant of the aggregation.

Replaying is the referee's correction mechanism. A `HeadReferee` may move `SCORED → REPLAYED` only when at least one `ComplianceViolation` with `source_kind` equal to `MATCH_REVIEW` references this match; otherwise the call is rejected with `ERR_NO_REPLAY_GROUNDS`. On replay, the prior ranking points are reversed from each team's aggregate (which is to say: each team's `team_ranking_score` is recomputed against the now-smaller set of finalized matches), and the match remains in `REPLAYED`. A new `Match` row is created via the schedule-replay workflow to actually run the rematch. A `SCHEDULED` match can also be cancelled by the system as a cascade from a team's `DISQUALIFIED` or `WITHDRAWN` transition — `CANCELLED` is terminal.

Between matches, the field must be reset. The `FieldResetLog` created at score time sits in `IN_PROGRESS`. A `FieldResetCrew` member completes it (`IN_PROGRESS → COMPLETE`) — permitted when the parent match's `status` is `SCORED`, `FINALIZED`, or `REPLAYED` — which stamps `completed_at` with the current instant and computes `actual_seconds` as the difference in seconds between `completed_at` and `started_at`. Aborting (`IN_PROGRESS → ABORTED`) is permitted only when the parent match's `status` is `CANCELLED`.

A forward-looking read is also exposed. A caller may ask for a team's projected ranking; the server returns `projected_ranking_score`, `projected_ranking_tie_break`, and `projected_matches_played` computed by the **forward_looking** variant of `team_ranking_score` — it includes `SCORED`-but-not-yet-`FINALIZED` matches in the average, so the projection during the score-to-finalize window differs from the pinned aggregate. The projected read is read-only and never writes.

### 3.6. Alliance Selection and the Snake Draft

Once every `QUALIFICATION` match is in `FINALIZED` or `REPLAYED` — anything else triggers `ERR_MATCHES_OPEN` (HTTP 409) — the director opens alliance selection. The event moves `MATCHES_RUNNING → ALLIANCE_SELECTION`; the server creates `AllianceSelectionRound` number 1 in `OPEN` status, and the `seed_alliance_captains` calculation runs.

The captain-seeding rule selects the top 8 captains. The candidate pool is every `CONFIRMED` team with `matches_played` at least 1 (the `MIN_MATCHES_FOR_SEEDING` constant). Candidates are sorted by `ranking_score` descending, then `ranking_tie_break` descending, then `team_number` ascending, then `created_at` ascending — `id` is never used as a tie-breaker. The first 8 teams of that sorted list become captains; for each, an `Alliance` row is created with `seed` equal to the 1-based position in the sorted list, `captain_team_id` equal to the team's id, and `status` equal to `FORMING`. If the candidate pool has fewer than 8 teams the entire operation is rejected with `ERR_INSUFFICIENT_CAPTAINS` (HTTP 409).

Picks proceed as a snake draft. Round 1 walks captains in ascending `seed` order (seed 1 picks first, seed 8 picks last); round 2 walks them in descending `seed` order (seed 8 picks first, seed 1 picks last). At any moment, the `AllianceSelectionRound` exposes `current_captain_team_id`, which identifies the team whose pick is due. When round 1 completes, the system automatically creates `AllianceSelectionRound` number 2 in `OPEN` status; when round 2 completes, every `Alliance` still in `FORMING` flips to `SEALED`. Sealing has a side effect on the captain: `is_alliance_captain` flips to true for each `captain_team_id` on a sealed alliance.

A pick is an OCC-guarded write: the captain's client submits `team_id` (the team they wish to add) plus `expected_round_version` matching the current `AllianceSelectionRound.version`; a stale round view is rejected with `ERR_STALE_VERSION`. The team being picked must satisfy three eligibility conditions simultaneously: their `registration_status` is `CONFIRMED`, they are not themselves a captain (`is_alliance_captain` is false), and they are not already on another alliance — that is, their id does not appear as `captain_team_id`, `pick1_team_id`, or `pick2_team_id` on any `FORMING` or `SEALED` alliance of this event. Picking an ineligible team is rejected with `ERR_PICK_INELIGIBLE` (HTTP 422). Independently, the acting `TeamLead` must be the captain whose pick is currently due — their `Person.id` (via their team's id) must match `current_captain_team_id` — else `ERR_OUT_OF_TURN` (HTTP 409). On success the chosen team is written into the alliance's `pick1_team_id` (round 1) or `pick2_team_id` (round 2), `current_captain_team_id` advances to the next seed in the snake order, and the round's `version` increments by 1. A round completes when all 8 alliances have made their pick for that round; on round-2 completion, every `FORMING` alliance flips to `SEALED`.

An `Alliance` transitions out of `SEALED` only through the playoff bracket: losing a playoff series moves it `SEALED → ELIMINATED`; winning the finals moves it `SEALED → CHAMPION`, and the latter cascade flips `qualified_for_championship` to true on every member team — captain, pick 1, and pick 2.

Closing alliance selection moves the event `ALLIANCE_SELECTION → AWARDS`. Preconditions: both round 1 and round 2 of `AllianceSelectionRound` must be in `COMPLETE` status (else `ERR_SELECTION_INCOMPLETE`, HTTP 409), and every `PLAYOFF` match must be `FINALIZED` or `REPLAYED`.

### 3.7. Awards, Judging, and Interviews

Awards are managed by the `JudgeAdvisor`. Opening an award requires `award_kind` — one of `CHAIRMANS`, `ENGINEERING_INSPIRATION`, `ROOKIE_ALL_STAR`, `WOODIE_FLOWERS`, `DEANS_LIST`, `SAFETY`, `CREATIVITY`, `QUALITY`, `INNOVATION`, `GRACIOUS_PROFESSIONALISM` — and `requires_interview` (a boolean; by convention true for `CHAIRMANS`, `ENGINEERING_INSPIRATION`, and `DEANS_LIST`). An `Award` is born in `OPEN` status with `winner_team_id` null. Beginning judging moves it `OPEN → JUDGING` and is permitted only while the event is in `MATCHES_RUNNING`, `ALLIANCE_SELECTION`, or `AWARDS`.

For awards that require interviews, the `JudgeAdvisor` proposes `InterviewSlot` rows by supplying `team_id`, `judge_id` (a `Person` whose `role_kind` is `JUDGE` and whose `screening_status` is `CLEARED`), `starts_at`, and `duration_minutes` (at least 5). The slot is born in `PROPOSED`. Confirmation is by the `TeamLead` of the team being interviewed; the lead's `Person.team_id` must equal the slot's `team_id`. Confirming a slot checks for judge double-booking: no other `CONFIRMED` slot for the same judge may overlap in time, where overlap is defined on half-open intervals `[starts_at, starts_at + duration_minutes)` — two slots that share only an endpoint do not overlap. A conflicting confirm is rejected with `ERR_JUDGE_DOUBLE_BOOKED` (HTTP 409). Completion is by the `Judge` whose `id` matches the slot's `judge_id`; on completion the slot moves `CONFIRMED → COMPLETED` and the `score` field is set from the payload — an integer from 0 to 100 inclusive. A slot may also be cancelled by the `JudgeAdvisor` while it is `PROPOSED` (`PROPOSED → CANCELLED`), or marked no-show by the assigned `Judge` once the current clock has passed `starts_at` plus `duration_minutes` (`CONFIRMED → NO_SHOW`).

Deciding an award moves it `JUDGING → DECIDED`. If the award's `requires_interview` is true, at least one `InterviewSlot` for the award must be in `COMPLETED` status — otherwise the call is rejected with `ERR_INTERVIEW_REQUIRED` (HTTP 422). The `award_winner_selection` calculation then runs and must produce a non-null winner; an empty eligible pool rejects the decide call with `ERR_NO_ELIGIBLE_TEAMS` (HTTP 409) and the award remains in `JUDGING`. On success, `winner_team_id` is written. If the `award_kind` is `CHAIRMANS`, the winning team's `qualified_for_championship` immediately flips to true as a cascade — the chairmans winner does not wait for the championship waterfall.

The winner-selection rule branches on `award_kind`. For an award with `requires_interview` true, the eligible pool is every team that has at least one `COMPLETED` interview slot for this award; each team's score is the arithmetic mean of its completed-interview `score` values, and the team with the highest average wins. For `SAFETY`, the eligible pool is every `CONFIRMED` team, and the score is the negative of the severity-weighted count of that team's unresolved violations — the team with the fewest open violations wins, with severity-weighted count as the tie-breaker inside the same open-count. For `ROOKIE_ALL_STAR`, the eligible pool is every `CONFIRMED` team flagged as a rookie, and the score is the team's `ranking_score`. For all other kinds, the eligible pool is every `CONFIRMED` team and the score is the team's `ranking_score`. Across all branches, final ties are broken by `ranking_score` descending, then `ranking_tie_break` descending, then `team_number` ascending, then `created_at` ascending.

Presentation is the last award step. An `EventDirector` moves `DECIDED → PRESENTED`, which is permitted only while the event is in `AWARDS` status. `PRESENTED` is terminal.

### 3.8. Championship Qualification and Travel Reimbursement

Closing the event moves `AWARDS → CLOSED`. Preconditions: every `Award` must be in `PRESENTED` (else `ERR_AWARDS_PENDING`, HTTP 409) and `outstanding_violation_count` must be zero. On success the `championship_qualification_run` calculation runs as a waterfall over the event's `championship_slots`.

The waterfall fills slots in priority order. Bucket 1: the `CHAIRMANS` award winner — if that award is `PRESENTED` and has a non-null `winner_team_id`, that team takes one slot. Bucket 2: the `ENGINEERING_INSPIRATION` winner, similarly, but only if that team has not already been awarded a slot in bucket 1. Bucket 3: the three members of the `CHAMPION` alliance — `captain_team_id`, `pick1_team_id`, `pick2_team_id` — each takes a slot in that order, skipping any team already awarded and skipping null picks. Bucket 4: every remaining `CONFIRMED` team not yet awarded, sorted by `ranking_score` descending, `ranking_tie_break` descending, `team_number` ascending, `created_at` ascending, taking slots in order until none remain. Each team's `qualified_for_championship` is written exactly once: true for every team that received a slot, false otherwise. Teams that already had `qualified_for_championship` set to true by an earlier cascade — a `CHAIRMANS` decide, a `CHAMPION` alliance — still consume a slot in the waterfall so the slot counts remain honest.

Once a team is qualified, it can book travel against the championship. A `TeamLead` creates a `TravelBooking` by supplying `mode` (`AIR`, `RAIL`, `BUS`, or `SELF_DRIVE`), `booked_at`, and `cost_cents` (non-negative). The booking is born in `PENDING` status. Approval is by a `TravelOfficer` and is gated on two things: the team's `qualified_for_championship` must be true (else `ERR_NOT_QUALIFIED`, HTTP 409), and the computed reimbursement must be strictly greater than zero. Approval moves the booking `PENDING → APPROVED` and writes `reimbursed_cents` from the `travel_reimbursement` calculation.

The reimbursement formula is **marginal** and tiered, with mode-specific caps. The cap is 1500000 cents for `AIR`, 800000 cents for `RAIL`, 400000 cents for `BUS`, and 300000 cents for `SELF_DRIVE`. The eligible amount is the smaller of `cost_cents` and the mode's cap — a booking whose `cost_cents` exceeds the mode's cap is rejected at validation time with `ERR_REIMBURSEMENT_CAP_EXCEEDED` (HTTP 422), so the cap check fires before the formula runs. Tiering then applies: the first 200000 cents of the eligible amount are reimbursed at 80 percent; any remainder above 200000 cents is reimbursed at 50 percent. Each tier's reimbursement is computed separately and rounded to a whole cent before the two tiers are summed — so the rounding is per-tier, not sum-then-round. For example, a booking of 250000 cents eligible yields 200000 × 0.80 = 160000 cents from tier 1 plus 50000 × 0.50 = 25000 cents from tier 2, totalling 185000 cents. The forbidden average-rate misreading — apply 50 percent to the entire eligible amount — would yield 125000 cents on the same booking and is not the specified behaviour.

After approval, the officer marks the booking `APPROVED → PAID` once disbursement is complete. Denial moves `PENDING → DENIED` and writes `reimbursed_cents` to zero. `PAID` and `DENIED` are terminal.

### 3.9. Cascade Reference and Knock-On Effects

Several operations emit cascades that extend well beyond the entity being mutated. They are collected here so that an implementer can verify each one.

- **Opening registration** runs `event_posture`.
- **Locking registration** withdraws every team still in `PENDING_PAYMENT` or `PAYMENT_CLEARED`, recomputes `registered_team_count`, and increments `FrcEvent.version` by 1.
- **Opening build season** arms the `KICKOFF` milestone.
- **Opening inspection** has no side effects beyond the event status.
- **Starting matches** runs `generate_match_schedule` and increments `FrcEvent.version` by 1.
- **Opening alliance selection** creates `AllianceSelectionRound(1)` in `OPEN` and seeds 8 captains.
- **Closing alliance selection** has no side effects.
- **Closing the event** runs `championship_qualification_run` and recomputes every team's `qualified_for_championship`.
- **Marking payment cleared** has no side effects.
- **Submitting a roster** has no side effects.
- **Confirming a team** increments `registered_team_count` by 1 and recomputes `cleared_mentor_count`.
- **Withdrawing a team** (from `CONFIRMED`) decrements `registered_team_count`, flips the team's `STAGED`/`AT_FIELD` queue slots to `NO_SHOW`, and flips the team's `PROPOSED`/`CONFIRMED` interview slots to `CANCELLED`.
- **Disqualifying a team** decrements `registered_team_count`, cancels every `SCHEDULED` match the team appears in (with replays to be scheduled), cancels every interview slot for the team, and clears the team's slots on any `FORMING` alliance.
- **Approving a screening** sets `decision` to `APPROVE`, sets `screening_expires_at`, recomputes posture, recomputes `cleared_mentor_count`, and increments `Person.version` by 1.
- **Rejecting a screening** recomputes posture and, if the person was a `MENTOR` whose team was `ROSTER_SUBMITTED`, reverts the team to `PAYMENT_CLEARED`.
- **Screening expiry** (system cron on every posture recompute and on clock advances) transitions every `CLEARED` person whose `screening_expires_at` has been reached to `EXPIRED`; if that was the team's last cleared mentor and the team is `CONFIRMED`, posture is recomputed.
- **Submitting a part order** stamps `submitted_at` and recomputes `order_total_cents`.
- **Approving / rejecting / placing / receiving / cancelling a part order** has no additional side effects.
- **Submitting a robot inspection** has no side effects.
- **Passing a robot inspection** flips the team's `robot_inspection_status` to `PASSED` and supersedes any other `SUBMITTED` inspections for the same team.
- **Failing a robot inspection** flips the team's `robot_inspection_status` to `FAILED`, creates an `INSPECTION` / `MAJOR` / `OPEN` violation, and recomputes `outstanding_violation_count`.
- **Opening a violation** recomputes `outstanding_violation_count` and `posture`.
- **Acking a violation** has no side effects.
- **Resolving a violation** recomputes `outstanding_violation_count` and `posture`.
- **Escalating a violation** recomputes `posture`.
- **Queueing a match** flips every queue slot to `STAGED`.
- **Taking the field** flips every queue slot to `ON_FIELD`.
- **Scoring a match** runs `score_match` (provisional), runs `ranking_points` if `QUALIFICATION`, releases every queue slot, and creates a `FieldResetLog` in `IN_PROGRESS`.
- **Finalizing a match** re-runs `score_match` (final, with cards), increments each participating team's `matches_played`, and recomputes each team's `ranking_score` and `ranking_tie_break`.
- **Replaying a match** reverses ranking points by recomputing team aggregates against the reduced set; a new `Match` row is scheduled separately.
- **Cancelling a match** (system cascade from team disqualify/withdraw) has no further effects.
- **Marking a queue slot at-field** stamps `arrived_at`.
- **Completing a field-reset log** stamps `completed_at` and computes `actual_seconds` as the difference from `started_at`.
- **Aborting a field-reset log** has no further effects.
- **An alliance sealing** flips `is_alliance_captain` to true on each captain.
- **An alliance winning the finals** flips `qualified_for_championship` to true on every member team.
- **A selection round completing** opens round 2 (if it was round 1) or seals every `FORMING` alliance (if it was round 2).
- **Submitting a pick** writes the pick onto the alliance, advances `current_captain_team_id`, increments the round's `version`, and may complete the round.
- **Beginning judging / deciding / presenting an award** — decide additionally writes `winner_team_id` and, for `CHAIRMANS`, flips the winner's `qualified_for_championship` to true.
- **Confirming an interview slot** has no side effects beyond state.
- **Completing an interview slot** records `score`.
- **Cancelling or no-showing an interview slot** has no side effects.
- **Approving a travel booking** writes `reimbursed_cents` from the marginal-tiered calculation.
- **Marking a booking paid** has no side effects.
- **Denying a booking** writes `reimbursed_cents` to zero.
- **Advancing the logical clock** runs `screening_expiry`.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201. Endpoints that mutate, transition, or read an existing resource return HTTP 200. Error responses use the 4xx status named in §5. Unless the request body explicitly carries an OCC field (see §2.4), no version field is accepted. The table below is a summary only — request and response payloads are described in §3 next to the owning workflow.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|---------------------|
| POST | /frc-events | Create a new FRC event | EventDirector |
| GET | /frc-events | List events | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor, Scorekeeper, QueueManager, HeadReferee, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, Judge |
| GET | /frc-events/{eventId} | Get one event | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor, Scorekeeper, QueueManager, HeadReferee, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, Judge |
| POST | /frc-events/{eventId}/open-registration | SETUP → REGISTRATION_OPEN | EventDirector |
| POST | /frc-events/{eventId}/lock-registration | REGISTRATION_OPEN → REGISTRATION_LOCKED; withdraw unpaid teams | EventDirector |
| POST | /frc-events/{eventId}/open-build-season | REGISTRATION_LOCKED → BUILD_SEASON | EventDirector |
| POST | /frc-events/{eventId}/open-inspection | BUILD_SEASON → INSPECTION | EventDirector |
| POST | /frc-events/{eventId}/start-matches | INSPECTION → MATCHES_RUNNING; generates qualification schedule (OCC) | EventDirector |
| POST | /frc-events/{eventId}/open-alliance-selection | MATCHES_RUNNING → ALLIANCE_SELECTION | EventDirector |
| POST | /frc-events/{eventId}/close-alliance-selection | ALLIANCE_SELECTION → AWARDS | EventDirector |
| POST | /frc-events/{eventId}/close-event | AWARDS → CLOSED; championship waterfall | EventDirector |
| POST | /frc-events/{eventId}/milestones | Create a build-season milestone | EventDirector |
| GET | /frc-events/{eventId}/milestones | List milestones | EventDirector, RegistrationOfficer, TeamLead, ProcurementOfficer |
| GET | /frc-events/{eventId}/milestones/{milestoneId} | Get one milestone | EventDirector, RegistrationOfficer, TeamLead, ProcurementOfficer |
| POST | /frc-events/{eventId}/milestones/{milestoneId}/mark-passed | Milestone SCHEDULED/ARMED → PASSED | EventDirector |
| POST | /frc-events/{eventId}/teams | Register a team | RegistrationOfficer |
| GET | /frc-events/{eventId}/teams | List teams | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor, Scorekeeper, QueueManager, HeadReferee, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, Judge |
| GET | /frc-events/{eventId}/teams/{teamId} | Get one team | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor, Scorekeeper, QueueManager, HeadReferee, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, Judge |
| POST | /frc-events/{eventId}/teams/{teamId}/mark-payment-cleared | PENDING_PAYMENT → PAYMENT_CLEARED | RegistrationOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/submit-roster | PAYMENT_CLEARED → ROSTER_SUBMITTED | TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/confirm | ROSTER_SUBMITTED → CONFIRMED | RegistrationOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/withdraw | PENDING_PAYMENT or CONFIRMED → WITHDRAWN | TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/disqualify | CONFIRMED → DISQUALIFIED | EventDirector |
| POST | /frc-events/{eventId}/persons | Register a person | RegistrationOfficer, TeamLead |
| GET | /frc-events/{eventId}/persons | List persons | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor |
| GET | /frc-events/{eventId}/persons/{personId} | Get one person | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor |
| POST | /frc-events/{eventId}/persons/{personId}/screening-records | Submit a screening package | ScreeningOfficer |
| GET | /frc-events/{eventId}/persons/{personId}/screening-records | List screening records | EventDirector, ScreeningOfficer |
| GET | /frc-events/{eventId}/persons/{personId}/screening-records/{recordId} | Get one record | EventDirector, ScreeningOfficer |
| POST | /frc-events/{eventId}/persons/{personId}/screening-records/{recordId}/approve | Approve a screening (OCC) | ScreeningOfficer |
| POST | /frc-events/{eventId}/persons/{personId}/screening-records/{recordId}/reject | Reject a screening | ScreeningOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders | Create a part order (DRAFT) | TeamLead |
| GET | /frc-events/{eventId}/teams/{teamId}/part-orders | List orders for a team | EventDirector, TeamLead, ProcurementOfficer |
| GET | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId} | Get one order | EventDirector, TeamLead, ProcurementOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}/submit | DRAFT → SUBMITTED | TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}/approve | SUBMITTED → APPROVED | ProcurementOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}/reject | SUBMITTED → REJECTED | ProcurementOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}/place-with-vendor | APPROVED → VENDOR_PLACED | ProcurementOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}/receive | VENDOR_PLACED → RECEIVED | TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/part-orders/{orderId}/cancel | DRAFT or SUBMITTED → CANCELLED | TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/robot-inspections | Create an inspection (DRAFT) | Inspector |
| GET | /frc-events/{eventId}/teams/{teamId}/robot-inspections | List inspections | EventDirector, Inspector, LeadInspector, TeamLead |
| GET | /frc-events/{eventId}/teams/{teamId}/robot-inspections/{inspectionId} | Get one inspection | EventDirector, Inspector, LeadInspector, TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/robot-inspections/{inspectionId}/submit | DRAFT → SUBMITTED | Inspector |
| POST | /frc-events/{eventId}/teams/{teamId}/robot-inspections/{inspectionId}/pass | SUBMITTED → PASSED | LeadInspector |
| POST | /frc-events/{eventId}/teams/{teamId}/robot-inspections/{inspectionId}/fail | SUBMITTED → FAILED | LeadInspector |
| POST | /frc-events/{eventId}/teams/{teamId}/violations | Open a violation | HeadReferee, Inspector, LeadInspector, JudgeAdvisor |
| GET | /frc-events/{eventId}/teams/{teamId}/violations | List violations | EventDirector, HeadReferee, TeamLead |
| GET | /frc-events/{eventId}/teams/{teamId}/violations/{violationId} | Get one violation | EventDirector, HeadReferee, TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/violations/{violationId}/ack | OPEN → ACKED | TeamLead |
| POST | /frc-events/{eventId}/teams/{teamId}/violations/{violationId}/resolve | ACKED → RESOLVED | HeadReferee |
| POST | /frc-events/{eventId}/teams/{teamId}/violations/{violationId}/escalate | OPEN → ESCALATED | HeadReferee |
| POST | /frc-events/{eventId}/matches | Create a match (manual — playoff, replay) | EventDirector, Scorekeeper |
| GET | /frc-events/{eventId}/matches | List matches | EventDirector, Scorekeeper, QueueManager, HeadReferee, FieldResetCrew, TeamLead |
| GET | /frc-events/{eventId}/matches/{matchId} | Get one match | EventDirector, Scorekeeper, QueueManager, HeadReferee, FieldResetCrew, TeamLead |
| POST | /frc-events/{eventId}/matches/{matchId}/queue | SCHEDULED → QUEUED | QueueManager |
| POST | /frc-events/{eventId}/matches/{matchId}/take-field | QUEUED → ON_FIELD | QueueManager |
| POST | /frc-events/{eventId}/matches/{matchId}/score | ON_FIELD → SCORED; provisional score | Scorekeeper |
| POST | /frc-events/{eventId}/matches/{matchId}/finalize | SCORED → FINALIZED; final score with cards | HeadReferee |
| POST | /frc-events/{eventId}/matches/{matchId}/replay | SCORED → REPLAYED; reverses ranking points | HeadReferee |
| POST | /frc-events/{eventId}/matches/{matchId}/score-breakdowns | Attach a score breakdown | Scorekeeper |
| GET | /frc-events/{eventId}/matches/{matchId}/score-breakdowns | List score breakdowns | EventDirector, Scorekeeper, HeadReferee |
| POST | /frc-events/{eventId}/matches/{matchId}/queue-slots | Create a queue slot | QueueManager |
| GET | /frc-events/{eventId}/matches/{matchId}/queue-slots | List slots for a match | EventDirector, QueueManager, TeamLead |
| GET | /frc-events/{eventId}/matches/{matchId}/queue-slots/{slotId} | Get one slot | EventDirector, QueueManager, TeamLead |
| POST | /frc-events/{eventId}/matches/{matchId}/queue-slots/{slotId}/mark-at-field | STAGED → AT_FIELD | QueueManager |
| GET | /frc-events/{eventId}/matches/{matchId}/field-reset-logs | List reset logs | EventDirector, FieldResetCrew, QueueManager |
| GET | /frc-events/{eventId}/matches/{matchId}/field-reset-logs/{logId} | Get one reset log | EventDirector, FieldResetCrew, QueueManager |
| POST | /frc-events/{eventId}/matches/{matchId}/field-reset-logs/{logId}/complete | IN_PROGRESS → COMPLETE | FieldResetCrew |
| POST | /frc-events/{eventId}/matches/{matchId}/field-reset-logs/{logId}/abort | IN_PROGRESS → ABORTED (match CANCELLED only) | FieldResetCrew |
| POST | /frc-events/{eventId}/alliances | Create alliance (manual; rarely used) | EventDirector |
| GET | /frc-events/{eventId}/alliances | List alliances | EventDirector, HeadReferee, TeamLead, Scorekeeper |
| GET | /frc-events/{eventId}/alliances/{allianceId} | Get one alliance | EventDirector, HeadReferee, TeamLead, Scorekeeper |
| GET | /frc-events/{eventId}/alliance-selection-rounds | List selection rounds | EventDirector, TeamLead |
| GET | /frc-events/{eventId}/alliance-selection-rounds/{roundId} | Get one round | EventDirector, TeamLead |
| POST | /frc-events/{eventId}/alliance-selection-rounds/{roundId}/pick | Captain picks a team (OCC) | TeamLead |
| POST | /frc-events/{eventId}/awards | Open an award for judging | JudgeAdvisor |
| GET | /frc-events/{eventId}/awards | List awards | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/{eventId}/awards/{awardId} | Get one award | EventDirector, JudgeAdvisor, Judge, TeamLead |
| POST | /frc-events/{eventId}/awards/{awardId}/begin-judging | OPEN → JUDGING | JudgeAdvisor |
| POST | /frc-events/{eventId}/awards/{awardId}/decide | JUDGING → DECIDED; winner selection runs | JudgeAdvisor |
| POST | /frc-events/{eventId}/awards/{awardId}/present | DECIDED → PRESENTED | EventDirector |
| POST | /frc-events/{eventId}/awards/{awardId}/interview-slots | Propose an interview slot | JudgeAdvisor |
| GET | /frc-events/{eventId}/awards/{awardId}/interview-slots | List slots | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/{eventId}/awards/{awardId}/interview-slots/{slotId} | Get one slot | EventDirector, JudgeAdvisor, Judge, TeamLead |
| POST | /frc-events/{eventId}/awards/{awardId}/interview-slots/{slotId}/confirm | PROPOSED → CONFIRMED | TeamLead |
| POST | /frc-events/{eventId}/awards/{awardId}/interview-slots/{slotId}/complete | CONFIRMED → COMPLETED | Judge |
| POST | /frc-events/{eventId}/awards/{awardId}/interview-slots/{slotId}/cancel | PROPOSED → CANCELLED | JudgeAdvisor |
| POST | /frc-events/{eventId}/awards/{awardId}/interview-slots/{slotId}/no-show | CONFIRMED → NO_SHOW | Judge |
| POST | /frc-events/{eventId}/teams/{teamId}/travel-bookings | Create a booking (PENDING) | TeamLead |
| GET | /frc-events/{eventId}/teams/{teamId}/travel-bookings | List bookings | EventDirector, TeamLead, TravelOfficer |
| GET | /frc-events/{eventId}/teams/{teamId}/travel-bookings/{bookingId} | Get one booking | EventDirector, TeamLead, TravelOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/travel-bookings/{bookingId}/approve | PENDING → APPROVED; reimbursement runs | TravelOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/travel-bookings/{bookingId}/mark-paid | APPROVED → PAID | TravelOfficer |
| POST | /frc-events/{eventId}/teams/{teamId}/travel-bookings/{bookingId}/deny | PENDING → DENIED | TravelOfficer |
| GET | /frc-events/{eventId}/teams/{teamId}/projected-ranking | Forward-looking ranking projection (read-only) | EventDirector, TeamLead, Scorekeeper, HeadReferee |
| GET | /frc-events/teams/{teamId} | Get a Team by id (flat route) | EventDirector, RegistrationOfficer, TeamLead, Scorekeeper, HeadReferee, QueueManager, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, JudgeAdvisor, Judge, ScreeningOfficer |
| GET | /frc-events/persons/{personId} | Get a Person by id (flat route) | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor |
| GET | /frc-events/screening-records | List screening records (flat filtered) | EventDirector, ScreeningOfficer |
| GET | /frc-events/screening-records/{recordId} | Get a ScreeningRecord by id (flat route) | EventDirector, ScreeningOfficer |
| GET | /frc-events/teams | List teams (canonical filtered) | EventDirector, RegistrationOfficer, TeamLead, Scorekeeper, HeadReferee, QueueManager, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, JudgeAdvisor, Judge, ScreeningOfficer |
| GET | /frc-events/persons | List persons (canonical filtered) | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor |
| GET | /frc-events/teams-filtered | List teams (flat filtered) | EventDirector, RegistrationOfficer, TeamLead, Scorekeeper, HeadReferee, QueueManager, Inspector, LeadInspector, FieldResetCrew, TravelOfficer, ProcurementOfficer, JudgeAdvisor, Judge, ScreeningOfficer |
| GET | /frc-events/persons-filtered | List persons (flat filtered) | EventDirector, RegistrationOfficer, ScreeningOfficer, TeamLead, JudgeAdvisor |
| GET | /frc-events/milestones-flat | List milestones (flat filtered) | EventDirector, RegistrationOfficer, TeamLead, ProcurementOfficer |
| GET | /frc-events/matches-flat | List matches (flat filtered) | EventDirector, Scorekeeper, QueueManager, HeadReferee, FieldResetCrew, TeamLead |
| GET | /frc-events/milestones-flat/{milestoneId} | Get a BuildSeasonMilestone by id (flat route) | EventDirector, RegistrationOfficer, TeamLead, ProcurementOfficer |
| GET | /frc-events/part-orders | List part orders (flat filtered) | EventDirector, TeamLead, ProcurementOfficer |
| GET | /frc-events/part-orders/{orderId} | Get a PartOrder by id (flat route) | EventDirector, TeamLead, ProcurementOfficer |
| GET | /frc-events/robot-inspections | List robot inspections (flat filtered) | EventDirector, Inspector, LeadInspector, TeamLead |
| GET | /frc-events/robot-inspections/{inspectionId} | Get a RobotInspection by id (flat route) | EventDirector, Inspector, LeadInspector, TeamLead |
| GET | /frc-events/violations | List compliance violations (flat filtered) | EventDirector, HeadReferee, TeamLead |
| GET | /frc-events/violations/{violationId} | Get a ComplianceViolation by id (flat route) | EventDirector, HeadReferee, TeamLead |
| GET | /frc-events/matches-flat/{matchId} | Get a Match by id (flat route) | EventDirector, Scorekeeper, QueueManager, HeadReferee, FieldResetCrew, TeamLead |
| GET | /frc-events/alliances-flat | List alliances (flat filtered) | EventDirector, HeadReferee, TeamLead, Scorekeeper |
| GET | /frc-events/alliance-selection-rounds-flat | List alliance selection rounds (flat filtered) | EventDirector, TeamLead |
| GET | /frc-events/awards-flat | List awards (flat filtered) | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/alliances-flat/{allianceId} | Get an Alliance by id (flat route) | EventDirector, HeadReferee, TeamLead, Scorekeeper |
| GET | /frc-events/alliances-filtered | List alliances (flat filtered) | EventDirector, HeadReferee, TeamLead, Scorekeeper |
| GET | /frc-events/alliance-selection-rounds-flat/{roundId} | Get an AllianceSelectionRound by id (flat route) | EventDirector, TeamLead |
| GET | /frc-events/alliance-selection-rounds-filtered | List alliance selection rounds (flat filtered) | EventDirector, TeamLead |
| GET | /frc-events/score-breakdowns | List score breakdowns (flat filtered) | EventDirector, Scorekeeper, HeadReferee |
| GET | /frc-events/score-breakdowns/{breakdownId} | Get a MatchScoreBreakdown by id (flat route) | EventDirector, Scorekeeper, HeadReferee |
| GET | /frc-events/queue-slots | List queue slots (flat filtered) | EventDirector, QueueManager, TeamLead |
| GET | /frc-events/queue-slots/{slotId} | Get a QueueSlot by id (flat route) | EventDirector, QueueManager, TeamLead |
| GET | /frc-events/field-reset-logs | List field reset logs (flat filtered) | EventDirector, FieldResetCrew, QueueManager |
| GET | /frc-events/field-reset-logs/{logId} | Get a FieldResetLog by id (flat route) | EventDirector, FieldResetCrew, QueueManager |
| GET | /frc-events/awards-flat/{awardId} | Get an Award by id (flat route) | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/awards-filtered | List awards (flat filtered) | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/interview-slots | List interview slots (flat filtered) | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/interview-slots/{slotId} | Get an InterviewSlot by id (flat route) | EventDirector, JudgeAdvisor, Judge, TeamLead |
| GET | /frc-events/travel-bookings | List travel bookings (flat filtered) | EventDirector, TeamLead, TravelOfficer |
| GET | /frc-events/travel-bookings/{bookingId} | Get a TravelBooking by id (flat route) | EventDirector, TeamLead, TravelOfficer |
| POST | /_clock/set_current_utc | Advance the logical clock (test-driving) | EventDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflow that raises them.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_TEAM_NOT_FOUND | 404 |
| ERR_PERSON_NOT_FOUND | 404 |
| ERR_RECORD_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_VIOLATION_NOT_FOUND | 404 |
| ERR_MATCH_NOT_FOUND | 404 |
| ERR_ALLIANCE_NOT_FOUND | 404 |
| ERR_AWARD_NOT_FOUND | 404 |
| ERR_SLOT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_MILESTONE_NOT_FOUND | 404 |
| ERR_RESET_LOG_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_EVENT_WRONG_STATUS | 409 |
| ERR_EVENT_FROZEN | 409 |
| ERR_SEGREGATION_VIOLATION | 403 |
| ERR_RECORD_NOT_PENDING | 409 |
| ERR_MENTOR_NOT_CLEARED | 422 |
| ERR_INSPECTOR_NOT_CLEARED | 422 |
| ERR_INSPECTOR_SELF | 422 |
| ERR_EVENT_FULL | 409 |
| ERR_TOO_FEW_TEAMS | 409 |
| ERR_STOP_BUILD_PASSED | 422 |
| ERR_NOT_BUILD_SEASON | 409 |
| ERR_ROBOT_OVERWEIGHT | 422 |
| ERR_FRAME_TOO_LARGE | 422 |
| ERR_BUMPERS_NONCOMPLIANT | 422 |
| ERR_INSPECTION_INCOMPLETE | 409 |
| ERR_MILESTONE_MISSING | 409 |
| ERR_MILESTONE_NOT_PASSED | 409 |
| ERR_MATCHES_OPEN | 409 |
| ERR_SELECTION_INCOMPLETE | 409 |
| ERR_AWARDS_PENDING | 409 |
| ERR_NO_GROUNDS | 409 |
| ERR_NO_REPLAY_GROUNDS | 409 |
| ERR_NO_ELIGIBLE_TEAMS | 409 |
| ERR_INTERVIEW_REQUIRED | 422 |
| ERR_PICK_INELIGIBLE | 422 |
| ERR_OUT_OF_TURN | 409 |
| ERR_INSUFFICIENT_CAPTAINS | 409 |
| ERR_INCOMPLETE_QUEUE | 409 |
| ERR_TEAM_NOT_AT_FIELD | 409 |
| ERR_MATCH_NOT_QUEUED | 409 |
| ERR_FIELD_NOT_RESET | 409 |
| ERR_FIELD_INTERVAL_VIOLATION | 422 |
| ERR_JUDGE_DOUBLE_BOOKED | 409 |
| ERR_SCORE_BREAKDOWN_MISSING | 409 |
| ERR_BUDGET_EXCEEDED | 402 |
| ERR_REIMBURSEMENT_CAP_EXCEEDED | 422 |
| ERR_NOT_QUALIFIED | 409 |
| ERR_DUPLICATE_TEAM_NUMBER | 409 |
| ERR_DUPLICATE_MATCH_NUMBER | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_ALREADY_TERMINAL | 409 |
