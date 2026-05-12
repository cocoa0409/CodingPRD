# Script Murder & Escape Room API — Product Requirements Document

## 1. Introduction

Script murder ("剧本杀") and escape-room venues operate at the intersection of theatrical content, physical room inventory, and social matchmaking. A single Saturday night involves dozens of moving parts: themes whose script content is licensed from external authors, rooms that must be physically reset between sessions, hosts and NPC actors who can only run one game at a time, and players who arrive in private teams or — increasingly — as strangers paired up by the platform's matching pool. This document specifies the API for a multi-venue chain operator that needs to schedule rooms, fill seats, run sessions, settle revenue across four distinct payee tiers, and moderate the post-session reviews that drive theme discovery.

The API treats time as a first-class concern. Slot creation must respect mandatory turnover gaps, matching pools must close at a fixed cutoff before the curtain goes up, deposit holds expire on a sliding clock, and reviews are accumulated into per-theme aggregates whose ordering of arithmetic is pinned to avoid drift between implementations. Because tests run faster than real time, an admin-only test-driving capability lets the harness advance the logical clock to a specified instant; all time-gated cascades fire deterministically off that one tick. Likewise, the gateway and content-system integrations are surfaced as inbound event endpoints so that payment confirmations and script-authorization revocations can be replayed without a real third party in the loop.

Settlement, finally, is the fiscal backbone. Every completed session contributes to an author royalty, a host commission, a venue revenue share, and a residual platform fee, all expressed in basis points and required to sum to exactly 10000. Refunds issued after a settlement run has been finalized cascade backward to flip that run into a reversed state — a deliberate choice that trades a small operational complication for a guarantee that no payout becomes inconsistent with the customer-facing ledger.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (the acting principal's identifier) and `X-User-Role` (the role string that scopes capability). When either header is missing, malformed, or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not authorised for the requested operation per §4 and the role descriptions below, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. The same error is returned when the role is correct in principle but the actor's identity does not own the targeted resource.

The platform recognises eight roles: `PlatformAdmin`, `VenueOperator`, `ScriptAuthor`, `Host`, `NPC`, `Player`, `ContentModerator`, and `PaymentGateway`. Roles divide into two identity families.

`PlatformAdmin`, `ContentModerator`, and `PaymentGateway` carry **opaque** identity: when `X-User-Role` is one of those three, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, on `AuditLogEntry.actor_user_id` and `AuditLogEntry.actor_role`) but does not compare it to any entity's `id`.

`VenueOperator`, `ScriptAuthor`, `Host`, `NPC`, and `Player` carry **entity-backed** identity. When `X-User-Role` is `Player`, `X-User-ID` is the `id` of the acting `Player`; ownership checks on any resource that references a `Player` (own bookings, own waitlist entries, own reviews) compare the resource's player foreign key to `X-User-ID`. When `X-User-Role` is `VenueOperator`, `X-User-ID` is the `id` of the acting `Venue`; for slot, booking, room, maintenance-window, and staff-assignment actions, the venue is resolved via the path's `venueId`, the slot's `venue_id`, or the booking's `slot.venue_id`, and that resolved id must equal `X-User-ID`. When `X-User-Role` is `Host` or `NPC`, `X-User-ID` is the `id` of the acting `StaffMember`; for `Host`, that staff member's `roles_held` must include `HOST`, and for `NPC` it must include `NPC`. When `X-User-Role` is `ScriptAuthor`, `X-User-ID` is the `id` of an acting `StaffMember` whose `chain_id` matches the targeted theme's `chain_id`; the v1 system does not maintain a separate `Theme.created_by` link, so chain co-membership is the sole authorship signal.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and may be any non-negative integer. List endpoints sort their results by `created_at` ascending. The `meta` block on list responses populates `limit`, `offset`, `total_count`, and `has_more`; non-list responses omit the four pagination fields.

### 2.4. Common Resource Properties

All persisted entities other than `AuditLogEntry` carry the same four common fields: `id` (a server-minted UUID, with no type prefix), `created_at` (ISO 8601 UTC with three fractional digits, set on insert and immutable thereafter), `updated_at` (ISO 8601 UTC with three fractional digits, refreshed on every successful mutation), and `version` (an integer initialised to 1 and incremented by 1 on every successful mutation). The `AuditLogEntry` record is append-only and carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Throughout this document, "bumps the version" and "refreshes `updated_at`" are shorthand for the same coupled write that occurs whenever any other field on the same row changes.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When the caller supplies `version` and it does not match the current row's `version`, the request is rejected with `ERR_INVALID_REQUEST` and no state changes. When the caller omits `version`, the version check is skipped and the mutation proceeds against whatever the current row holds. The `version` field is monotonically increased by exactly 1 on every successful mutation.

### 2.6. Time, Intervals, and Timezone Handling

All timestamps on the wire are ISO 8601 UTC. Comparisons inside the system are performed at second granularity. Every interval in the system — `MaintenanceWindow` `[starts_at, ends_at)`, `SessionSlot` `[starts_at, ends_at)`, and `SettlementRun` `[period_starts_at, period_ends_at)` — is closed-open: the lower bound is inclusive, the upper bound exclusive, and two intervals that share an endpoint do not collide. `Venue.timezone` is a free-form IANA timezone string (default `Asia/Shanghai`) used to interpret `business_hours` and to compute ISO weeks for staff weekly minute aggregation; `business_hours` is keyed by weekday integer where 0 is Monday and 6 is Sunday, with each value either `null` (the venue is closed that day) or an object with `open` and `close` fields formatted as `HH:MM`, where `open` must be strictly less than `close` on the same calendar day (overnight hours are not modeled in v1). For the `staff_weekly_minutes` aggregation, the ISO week (Monday through Sunday) of an assignment is determined in the timezone of the chain's representative venue — specifically, the first `Venue` row in the chain ordered by `created_at` ascending, used as a deterministic tie-break in case multiple venues exist.

Real time progresses through a logical clock that an admin-only test-driving capability advances to a supplied `to_timestamp` instant; all time-gated cascades — match-deadline lapses, deposit-hold TTL expirations, and waitlist promotion sweeps that follow them — fire deterministically off that single tick.

### 2.7. Hierarchical Cascades and Audit

Many state transitions in this system mutate more than one entity. Whenever a transition's side effects touch additional rows — a slot cancellation that voids its bookings, a venue suspension that voids its slots, a refund that reverses a settlement run — every affected row's `version` is bumped by 1 and its `updated_at` refreshed. Cascades are immediate: they execute atomically within the same request that triggered the originating transition, never as deferred background work. Settlement creation and waitlist promotion sweeps are likewise explicit endpoint-driven operations rather than scheduled jobs.

A subset of mutations are recorded in the append-only audit log. Specifically, the system writes an `AuditLogEntry` for `BOOKING_CREATED` (on first entry into `CONFIRMED`; idempotent re-confirmations of the same booking do not duplicate the entry), `BOOKING_CANCELLED`, `BOOKING_NO_SHOW_MARKED`, `BOOKING_REFUNDED`, `REVIEW_SUBMITTED`, `REVIEW_PUBLISHED`, `REVIEW_REJECTED`, `REVIEW_HIDDEN`, `SETTLEMENT_FINALIZED`, and `SETTLEMENT_REVERSED`. Each entry records the request's `actor_user_id` and `actor_role`, the polymorphic `subject_entity_type` (one of `Booking`, `Review`, or `SettlementRun`) and `subject_entity_id`, the captured `action`, and a full pre/post `payload_snapshot` of the subject at the moment of action.

### 2.8. Nested Path Validation

Endpoints whose URL path nests multiple identifiers — for example, a maintenance-window endpoint mounted under a venue under a room — validate identifiers strictly left to right. The outer `venueId` is checked first and yields `ERR_VENUE_NOT_FOUND` if absent; only then is `roomId` checked, yielding `ERR_ROOM_NOT_FOUND`; and so on through `slotId`, `bookingId`, `entryId`, `reviewId`, `staffId`, `assignmentId`, `runId`, `themeId`, and `playerId`, each producing the entity-specific not-found error code listed in §5. Nested existence checks always run before any role, state, or business-rule checks on the same request.

### 2.9. Validation Priority Order

When multiple validation classes apply to the same request, they are evaluated in the following order, and the first one to fail is the one whose error is returned. Header well-formedness comes first, producing `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Role permission comes second, producing `ERR_INSUFFICIENT_PERMISSIONS`. Path-segment existence (left-to-right) comes third, producing the entity-specific 404 codes. Venue active-status comes fourth, producing `ERR_VENUE_NOT_ACTIVE` for any mutation under a venue that is not in `ACTIVE` status. Target resource state comes fifth, producing the state-specific 409 codes (such as `ERR_SESSION_NOT_OPEN_FOR_CONFIRM`, `ERR_SESSION_NOT_OPEN_FOR_CANCEL`, `ERR_SESSION_NOT_LIVE`, `ERR_SESSION_NOT_MATCHED`, `ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER`, `ERR_REFUND_REQUIRES_COMPLETED_SESSION`, `ERR_REVIEW_REVISION_LIMIT`, `ERR_THEME_HAS_FUTURE_SESSIONS`, `ERR_VENUE_HAS_OPEN_SESSIONS`, `ERR_HANDOFF_AFTER_LIVE`, `ERR_SETTLEMENT_HAS_OPEN_SESSIONS`, `ERR_SETTLEMENT_ALREADY_FINALIZED`, `ERR_REVIEW_ALREADY_MODERATED`, and `ERR_WAITLIST_ALREADY_PROMOTED`). Cross-entity referential integrity comes sixth, producing `ERR_THEME_ROOM_INCOMPATIBLE`, `ERR_STAFF_CHAIN_MISMATCH`, or `ERR_SETTLEMENT_CHAIN_MISMATCH`. Player-safety checks come seventh, producing `ERR_PLAYER_BANNED`. Match-preference filtering comes eighth, producing `ERR_MATCH_PREFERENCE_REJECTED`. Room/slot temporal overlap comes ninth, producing `ERR_SLOT_OVERLAP_CONFLICT` or `ERR_MAINTENANCE_OVERLAP_CONFLICT`. Staff temporal overlap comes tenth, producing `ERR_STAFF_OVERLAP_CONFLICT`. Staff qualification matching comes eleventh, producing `ERR_STAFF_QUALIFICATION_MISMATCH`. Staff weekly-minutes accumulation comes twelfth, producing `ERR_STAFF_WEEKLY_LIMIT_EXCEEDED`. Substitution depth comes thirteenth, producing `ERR_SUBSTITUTE_DEPTH_EXCEEDED`. Slot capacity comes fourteenth, producing `ERR_SLOT_FULL`. Theme publication state comes fifteenth, producing `ERR_THEME_NOT_PUBLISHED`. Review eligibility comes sixteenth, producing `ERR_REVIEW_NOT_ELIGIBLE` or `ERR_REVIEW_DUPLICATE`. Revenue-split bps sum comes seventeenth, producing `ERR_REVENUE_SPLIT_INVALID`. Refund-amount cap comes eighteenth, producing `ERR_REFUND_EXCEEDS_PAID`. Generic body validation (missing fields, type mismatches, malformed timestamps, out-of-range integers, invalid enum values) is folded into `ERR_INVALID_REQUEST` and is checked alongside whichever business rule first reaches it; in particular, the optional-`version` mismatch on a mutating endpoint returns `ERR_INVALID_REQUEST`.

### 2.10. Money, Basis Points, and Rounding

All monetary amounts are integer cents. Per-seat prices, deposit hold amounts, and refund amounts are stored as `*_cents` integer fields. Revenue shares — `revenue_share_bps`, `author_royalty_bps`, `host_commission_bps`, `platform_fee_bps`, and the per-staff `commission_bps_override` and per-theme `author_royalty_bps_override` — are integers expressed in basis points, where 10000 bps equals 100%. At venue create and venue update time, and again at every settlement finalize, the four base bps fields on each affected venue must sum to exactly 10000; any other sum (after applying applicable per-theme or per-staff overrides) yields `ERR_REVENUE_SPLIT_INVALID`. All revenue-allocation multiplications floor to the integer cent. Review-aggregate scores are the only decimal quantity in the system: they are computed to one decimal place using round-half-up.

### 2.11. Concurrency Race Outcomes

Six high-traffic races are serialised explicitly. When two players race to book the last seats on a `PUBLIC_TEAMUP` slot such that, taken together, their bookings would push `confirmed_seat_count` above `theme.max_players`, the first writer wins on the slot's confirmed-seat counter and the loser is rejected with `ERR_SLOT_FULL` at HTTP 409. When a player cancels a booking while a venue operator simultaneously starts the same slot, the first writer wins on the slot's `schedule_status`; if the start wins (advancing to `LIVE`), the player's cancel sees a `schedule_status` no longer equal to `SCHEDULED` and is rejected with `ERR_SESSION_NOT_OPEN_FOR_CANCEL` at HTTP 409. When two venue operators race to assign the same staff member to two overlapping slots in the same chain, the first assignment is created and the second is rejected with `ERR_STAFF_OVERLAP_CONFLICT` at HTTP 409 because its proposed interval would collide with the winner. When two cancellations free seats simultaneously and both trigger a waitlist-promotion sweep, the first writer wins on the chosen `WaitlistEntry`'s status (which becomes `PROMOTED`) and the second sweep, observing `PROMOTED`, skips that entry and continues to the next eligible candidate; double-promotion is prevented and the late sweep that finds no eligible entry where it expected one returns `ERR_WAITLIST_ALREADY_PROMOTED` at HTTP 409 only when surfaced as an explicit operation. When a refund and a settlement-finalize race on the same `SettlementRun`, the first writer wins on the run's status: if finalize wins first, the refund cascades to flip the run to `REVERSED`; if the refund wins first, finalize observes the revised `net_revenue_cents` and pins post-refund payouts. The losing finalize attempt returns `ERR_SETTLEMENT_ALREADY_FINALIZED` at HTTP 409. When two content moderators moderate the same review concurrently, the first decision wins on `Review.status` leaving `PENDING_MODERATION` and the second attempt is rejected with `ERR_REVIEW_ALREADY_MODERATED` at HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Venue, Chain, and Room Inventory

A `PlatformAdmin` registers a venue by supplying `chain_id`, `name`, an optional `timezone` (defaulting to `Asia/Shanghai`), `business_hours`, `deposit_policy_cents`, and the four basis-point fields `revenue_share_bps`, `author_royalty_bps`, `host_commission_bps`, and `platform_fee_bps`. The `name` must be one to 120 characters and unique within the same `chain_id`; venues sharing a `chain_id` form a chain for the purposes of theme reuse, staff contracting, and settlement scope. The `deposit_policy_cents` is a per-seat hold amount stored as integer cents, bounded between zero and one million inclusive. The four bps fields must each lie in the range zero through ten thousand inclusive; their sum is checked at creation time and again on every update — if it is not exactly 10000, the request is rejected with `ERR_REVENUE_SPLIT_INVALID`. A new venue starts in `ACTIVE`. When a `PlatformAdmin` later updates the venue with new `business_hours`, `deposit_policy_cents`, or any of the four bps fields (each optional and individually patchable), the sum is re-validated; an optional `version` may be supplied to assert concurrency.

`PlatformAdmin` operators steer the venue lifecycle. Suspending a venue moves it from `ACTIVE` to `SUSPENDED`; the room records under it remain in their own `ACTIVE` status (room status is independent), but every `SessionSlot` in that venue with `schedule_status` equal to `SCHEDULED` is auto-cancelled by cascade, every `Booking` under those slots in `PENDING_DEPOSIT` or `CONFIRMED` is cascaded to `CANCELLED` with `cancellation_initiator` set to `VENUE`, and deposits are fully refunded under the venue-or-system policy described in §3.6. Resuming a venue moves it from `SUSPENDED` back to `ACTIVE` with no cascading effect. Closing a venue is terminal and may be initiated from either `ACTIVE` or `SUSPENDED`, but only when no `SessionSlot` in the venue still has `schedule_status` of `SCHEDULED` or `LIVE`; otherwise the request is rejected with `ERR_VENUE_HAS_OPEN_SESSIONS`. Once `CLOSED`, the venue cannot transition further. Any mutation under a venue not in `ACTIVE` (creating rooms, maintenance windows, slots, or bookings) is rejected with `ERR_VENUE_NOT_ACTIVE`.

A `VenueOperator` adds rooms to their own venue. A room's `name` is required and unique within `venue_id`. The `capacity_min` is the minimum number of simultaneous players the room supports and must be at least 1; `capacity_max` must be at least `capacity_min` and at most 20. A `turnover_minutes` field, defaulting to 30 and bounded between 0 and 240 inclusive, encodes the mandatory cleaning and reset gap that must elapse after a session in this room ends before the next session may begin. A room starts in `ACTIVE` and may be retired to `RETIRED` — both values are exposed as `Room.status`.

Maintenance windows belong to rooms. A `VenueOperator` schedules a window with `starts_at` and `ends_at` (the latter strictly greater than the former), an optional `reason` note, and a server-defaulted `status` of `SCHEDULED`. The server rejects a proposed window that collides with any existing slot or maintenance on the same room (the geometry is described in §3.4) with `ERR_MAINTENANCE_OVERLAP_CONFLICT`. A window's `status` may evolve to `ACTIVE` once its window has begun and to `CLOSED` thereafter.

### 3.2. Themes, Authoring, and Versioning

A `ScriptAuthor` creates a `Theme` in `DRAFT` status. The body carries `chain_id`, `title` (unique within `chain_id`), `genre` (one of `MYSTERY`, `HORROR`, `EMOTIONAL`, `SCIFI`, `COMEDY`, `PUZZLE`), `difficulty` (one of `EASY`, `MEDIUM`, `HARD`, `EXPERT`), `duration_minutes` (between 30 and 360 inclusive — the standard playtime per session), `min_players` (at least 1), `max_players` (at least `min_players` and at most 20), an optional `required_host_qualifications` array of qualification tags such as `DM_CERT` or `HORROR_SAFE`, an optional `required_npc_count` (defaulting to 0 and bounded between 0 and 10 inclusive), a `compatible_room_ids` array (which must be non-empty and may only contain room ids belonging to the same `chain_id`), `base_price_cents`, and an optional `author_royalty_bps_override`. Themes are chain-scoped, not venue-scoped: the same theme can be staged in any of the chain's compatible rooms. On creation, `current_version` is set to 1 and `status` is `DRAFT`.

Publishing a theme advances `Theme.status` from `DRAFT` to `PUBLISHED`; publication is rejected with `ERR_THEME_NO_COMPATIBLE_ROOM` if `compatible_room_ids` is empty and with `ERR_INVALID_REQUEST` if `min_players` exceeds `max_players`. The first publication does not change `current_version`, which remains 1. Once a theme is published, the author may issue a revision: this transition keeps `Theme.status` at `PUBLISHED` but increments `current_version` by 1. The body must explicitly set `bumps_version` to `true` (otherwise `ERR_INVALID_REQUEST`); existing `SessionSlot` rows retain their previously pinned `theme_version_pinned` value, while any new slot created after the revision pins the new `current_version`. Retiring a theme advances it to `RETIRED` from either `DRAFT` or `PUBLISHED`, but only when no `SessionSlot` exists with `theme_id` equal to this theme and `schedule_status` in `SCHEDULED` or `LIVE`; otherwise the request is rejected with `ERR_THEME_HAS_FUTURE_SESSIONS`. Slot creation on a theme not in `PUBLISHED` status — that is, on a `DRAFT` or `RETIRED` theme — is rejected with `ERR_THEME_NOT_PUBLISHED`.

If the upstream content system revokes authorization for a specific theme version, the inbound event endpoint receives `theme_id` and `revoked_version`. Any `SessionSlot` whose `theme_id` matches and whose `theme_version_pinned` equals the revoked version, and that is still in `schedule_status` of `SCHEDULED`, is auto-cancelled by cascade; downstream `Booking` rows under those slots are cancelled with `cancellation_initiator` of `VENUE` (mirroring the venue-suspension cascade).

### 3.3. Session Slot Scheduling — Two Parallel State Axes

The slot list endpoint additionally accepts the optional time-window query parameters `starts_after` and `starts_before` to restrict the returned set to slots whose `starts_at` falls within the requested range; these compose with the standard `limit` and `offset` parameters.

A `VenueOperator` creates a `SessionSlot` under a specific room (the parent room is captured on the slot as `room_id` for query convenience, alongside the denormalised `venue_id`), supplying `theme_id`, `starts_at`, an optional `price_cents` (defaulting to the theme's `base_price_cents` when omitted), `visibility` (either `PRIVATE_ONLY` for a single team booking all seats, or `PUBLIC_TEAMUP` for the matching pool to fill seats), `required_seats_for_launch`, and an optional `match_preferences` payload that is described in §3.5. The slot's `venue_id` is denormalised for query convenience, `theme_version_pinned` is set to the theme's current `current_version` at slot creation and remains pinned thereafter, and `ends_at` is computed as `starts_at` plus the theme's `duration_minutes` and is immutable. The `required_seats_for_launch` must satisfy the theme's `min_players` lower bound and `max_players` upper bound — that is, it must be at least the theme's minimum and at most the theme's maximum. The `match_deadline_at` is computed at slot creation as `starts_at` minus 60 minutes and stored on the slot. The slot starts with `schedule_status` of `SCHEDULED` and `match_status` of `OPEN`, with `confirmed_seat_count`, `gross_revenue_cents`, and `net_revenue_cents` initialised to 0.

Each `SessionSlot` carries two state axes that evolve in parallel. The schedule axis runs `SCHEDULED → LIVE → COMPLETED` along the happy path and `SCHEDULED → CANCELLED` on the off-ramp. The match axis, independent of schedule, runs `OPEN → MATCHED` when seats fill in time and `OPEN → MATCH_FAILED` when they do not. The cross-axis coupling is a single rule: starting the slot requires the match axis to read `MATCHED`. If a `VenueOperator` tries to start a slot whose match axis is still `OPEN`, the request is rejected with `ERR_SESSION_NOT_MATCHED`. Conversely, if the match-deadline cascade flips the match axis to `MATCH_FAILED`, the schedule axis is forced from `SCHEDULED` to `CANCELLED` by the same cascade.

Starting a slot — moving the schedule axis from `SCHEDULED` to `LIVE` — additionally requires that the current logical clock falls within the start window, defined as the closed interval bounded by `starts_at` minus `START_GRACE_MINUTES` and `starts_at` plus `START_GRACE_MINUTES`; outside that window the request is rejected with `ERR_OUTSIDE_START_WINDOW`. The owning venue must be in `ACTIVE` status (otherwise `ERR_VENUE_NOT_ACTIVE`), and every required `HOST` and `NPC` `StaffAssignment` for the slot must be in either `SCHEDULED` or `ACTIVE` status (otherwise `ERR_STAFFING_INCOMPLETE`). On success, all confirmed bookings remain `CONFIRMED` until check-in, and every `StaffAssignment` for the slot still in `SCHEDULED` cascades to `ACTIVE`.

Completing a slot — moving the schedule axis from `LIVE` to `COMPLETED` — requires every `HOST` and `NPC` `StaffAssignment` to be in `ACTIVE` or `HANDED_OFF` (otherwise `ERR_STAFFING_INCOMPLETE`). On success, every `Booking` in `CHECKED_IN` cascades to `SETTLED` (the per-seat `paid_amount_cents` is recognised as revenue and the deposit hold is released back to the player; the deposit release is **not** counted toward `refund_total_cents`). Every `Booking` still in `CONFIRMED` at the moment of completion — that is, players who confirmed but never checked in — cascades to `CANCELLED` with `cancellation_initiator` set to `NO_SHOW`; their deposits are forfeited to the venue under the no-show variant of the cancellation-refund policy, and the offending players have their `no_show_strikes` counter incremented (an `AuditLogEntry` with action `BOOKING_NO_SHOW_MARKED` is written). Every `StaffAssignment` in `ACTIVE` cascades to `COMPLETED`. The slot's `gross_revenue_cents` and `net_revenue_cents` are pinned at this point, and reviews become permitted on `SETTLED` bookings.

Cancelling a slot — moving the schedule axis from `SCHEDULED` to `CANCELLED` — may be triggered by the operator directly, by a venue suspension or closure cascade, or by a match-deadline cascade. The match axis may simultaneously flip to `MATCH_FAILED` if and only if the cancel was triggered by the match-deadline cascade; otherwise the match axis is left untouched. Every `Booking` in `PENDING_DEPOSIT` or `CONFIRMED` under the slot cascades to `CANCELLED` with `cancellation_initiator` of `VENUE` (when the trigger is operator or venue-suspension) or `SYSTEM_MATCH_FAIL` (when the trigger is match-deadline expiry); deposits are fully refunded under the venue-or-system variant of the cancellation-refund policy. Every `WaitlistEntry` in `QUEUED` for the slot cascades to `EXPIRED`. Every `StaffAssignment` in `SCHEDULED` cascades to `CANCELLED`.

The `confirmed_seat_count` is recomputed eagerly on every booking transition; it is the sum of `seat_count` across bookings in `CONFIRMED` for the slot. The `gross_revenue_cents` is the sum of `paid_amount_cents` across `SETTLED` bookings, finalised at completion. The `net_revenue_cents` equals `gross_revenue_cents` minus the running total of refunds across the slot's `REFUNDED` and partially-refunded `SETTLED` bookings; it is recomputed eagerly on every refund.

### 3.4. Room Time Geometry — Slot and Maintenance Overlap

The room is the physical resource around which all temporal conflict checks are organised. When a venue operator proposes a new session slot `P` in room `R`, the system computes `P`'s start as `P.starts_at` and `P`'s effective finish as `P.ends_at` plus the room's `turnover_minutes` — the turnover gap acts as a forward-extending exclusive guard that no following item may intrude upon. The proposed slot conflicts with an existing item `X` on the same room when `X.schedule_status` is in `SCHEDULED` or `LIVE` (for slots) or `X.status` is in `SCHEDULED` or `ACTIVE` (for maintenance), and when the maximum of the two starts is strictly less than the minimum of the two finishes. For an existing slot `X`, its effective finish is likewise `X.ends_at` plus `R.turnover_minutes`. For an existing maintenance window, its effective finish is its own `ends_at` — the turnover guard is **not** applied to maintenance windows. The slot-versus-slot case therefore extends the turnover guard on both sides, and the slot-versus-maintenance case extends it on the slot side only — a deliberately one-sided geometry that distinguishes maintenance from session footprint. A conflict on slot creation is rejected with `ERR_SLOT_OVERLAP_CONFLICT`; a conflict on maintenance creation is rejected with `ERR_MAINTENANCE_OVERLAP_CONFLICT`.

The staff-overlap geometry is intentionally simpler. Two staff assignments `A` and `B` for the same `staff_member_id` collide if the maximum of their slot starts is strictly less than the minimum of their slot ends. Touching back-to-back is allowed; no buffer minutes are modeled in v1, so the same host may move directly from one slot to another at the same venue or across venues in the same chain. Only assignments in `SCHEDULED` or `ACTIVE` block; assignments in `HANDED_OFF`, `COMPLETED`, or `CANCELLED` do not. Both interval checks operate on second-granularity ISO timestamps, and both are closed-open: an assignment ending at exactly the time another begins is permitted.

### 3.5. Player Identity, Match Preferences, and Booking Creation

A `Player` self-registers by supplying `display_name`, `gender` (one of `MALE`, `FEMALE`, `UNDISCLOSED`), `age` (between 12 and 99 inclusive), `experience_level` (one of `NOVICE`, `INTERMEDIATE`, `VETERAN`), and an optional `tier` (defaulting to `STANDARD`, with `VIP` as the alternative). A `PlatformAdmin` may also register on behalf. Player identity is recorded as `Player.id` and equals `X-User-ID` whenever the role is `Player`. The system tracks `no_show_strikes`, a count of `NO_SHOW` cancellations within the trailing `NO_SHOW_WINDOW_DAYS` interval; once `no_show_strikes` reaches `NO_SHOW_BAN_THRESHOLD`, new bookings and waitlist enqueues for that player are rejected. The player's `status` is either `ACTIVE` or `BANNED`.

Booking a session begins when a `Player` posts a `team_player_ids` array against a session slot. The acting player's id (which equals `X-User-ID`) is recorded as `lead_player_id` and must appear in the `team_player_ids` array. The server pins `seat_count` as the length of `team_player_ids`, computes `paid_amount_cents` as `seat_count` multiplied by the slot's `price_cents`, and computes `deposit_held_cents` as `seat_count` multiplied by the venue's `deposit_policy_cents`. The new booking enters `PENDING_DEPOSIT` with `cancellation_initiator` left null, `refund_total_cents` initialised to 0, and a server-stamped pair of timestamps.

At booking creation, the server enforces three safety filters in priority order. If the player is `BANNED` or has `no_show_strikes` at or above `NO_SHOW_BAN_THRESHOLD`, the request is rejected with `ERR_PLAYER_BANNED`. If the slot's `visibility` is `PUBLIC_TEAMUP`, the slot's `match_preferences` payload — set at slot creation and structured around gender, age range, and experience-level filters — is consulted; any incoming player whose demographics fall outside the configured preference yields `ERR_MATCH_PREFERENCE_REJECTED`. The capacity check then ensures that `confirmed_seat_count` plus the new booking's `seat_count` would not exceed the theme's `max_players`; if it would, the booking is rejected with `ERR_SLOT_FULL`. The capacity check is re-applied atomically at deposit confirmation.

### 3.6. Booking Lifecycle, Cancellation Policy, and No-Show Forfeiture

A booking's natural progression is `PENDING_DEPOSIT → CONFIRMED → CHECKED_IN → SETTLED`. Confirmation is driven either by the player's own action or — equivalently — by an inbound payment-gateway callback that carries the `booking_id` and an optional `idempotency_key`. The transition is idempotent: re-confirming the same booking with the same `idempotency_key` returns the same response without creating duplicate audit entries. Confirmation requires the slot to still be in `schedule_status` of `SCHEDULED` (otherwise `ERR_SESSION_NOT_OPEN_FOR_CONFIRM`), the post-confirm `confirmed_seat_count` to remain at or below `theme.max_players` (otherwise `ERR_SLOT_FULL`), the player to be `ACTIVE` and below the strike threshold (otherwise `ERR_PLAYER_BANNED`). On success, `Slot.confirmed_seat_count` is incremented by `seat_count`, an `AuditLogEntry` with action `BOOKING_CREATED` is emitted on the first such transition for this booking, and if the post-increment count meets or exceeds the slot's `required_seats_for_launch` while `match_status` is `OPEN`, the match axis cascades to `MATCHED`. Check-in advances `CONFIRMED` to `CHECKED_IN` and requires the slot to be `LIVE` (otherwise `ERR_SESSION_NOT_LIVE`); it is the venue operator's responsibility on the day. Settlement of the booking — the `CHECKED_IN → SETTLED` transition — is fired by the slot completion cascade described in §3.3.

A booking may also be cancelled. Player-initiated cancellation is allowed only while the slot is still in `schedule_status` of `SCHEDULED`; once the slot is `LIVE`, player cancellation is rejected with `ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER`. Operator-initiated cancellation, slot-driven cascade cancellation, venue-suspend or venue-close cascade cancellation, match-fail cascade cancellation, and the post-completion no-show cascade can each push a booking from `PENDING_DEPOSIT` or `CONFIRMED` to `CANCELLED`; in each case, the `cancellation_initiator` is recorded as `PLAYER`, `VENUE`, `SYSTEM_MATCH_FAIL`, or `NO_SHOW` to match the trigger. Slot's `confirmed_seat_count` decreases by the cancelled booking's `seat_count` if the booking had been `CONFIRMED`. If that decrease pushes the post-decrement count below `required_seats_for_launch` while `match_status` is `MATCHED` and the current logical clock is still earlier than `match_deadline_at`, the match axis demotes from `MATCHED` back to `OPEN`. If instead the current logical clock has already reached or passed `match_deadline_at`, the cancellation cascade flips the match axis to `MATCH_FAILED` (which in turn forces the schedule axis to `CANCELLED`). After every cancellation, the waitlist promotion sweep runs (see §3.7) and an `AuditLogEntry` with action `BOOKING_CANCELLED` is emitted.

The refund computed for each cancellation depends on `cancellation_initiator` and, in the player-cancellation case, on lead time. Define lead minutes as the minutes from the current logical clock to the slot's stored `starts_at`, treating the value as negative when the clock has already passed `starts_at`.

For a player-initiated cancellation of a still-`SCHEDULED` slot, three lead-time tiers apply. When lead minutes is at least `FREE_CANCEL_LEAD_MINUTES` (24 hours, or 1440 minutes), the deposit refund is the full `deposit_held_cents` and the paid refund is the full `paid_amount_cents`. When lead minutes is below that bound but still at least `LATE_CANCEL_LEAD_MINUTES` (2 hours, or 120 minutes), the deposit refund is the full `deposit_held_cents` and the paid refund is the floor of `paid_amount_cents` multiplied by `LATE_CANCEL_PAID_REFUND_BPS` (5000) divided by 10000 — that is, fifty percent of the paid amount, rounded down to the cent. When lead minutes is below `LATE_CANCEL_LEAD_MINUTES` (including any negative value), both the deposit refund and the paid refund are zero — the deposit is forfeited to the venue.

For a venue-initiated or system-initiated cancellation — `cancellation_initiator` of `VENUE` or `SYSTEM_MATCH_FAIL` — the refund is always the full deposit plus the full paid amount, regardless of lead minutes.

For a no-show cancellation — `cancellation_initiator` of `NO_SHOW`, fired by the slot completion cascade on a `CONFIRMED` booking that never reached `CHECKED_IN` — the deposit refund and the paid refund are both zero; the deposit is forfeited and the player's `no_show_strikes` is incremented.

For an operator-driven post-completion quality refund — the `SETTLED → REFUNDED` transition — the operator supplies `refund_amount_cents`; the deposit refund is zero (the deposit was already released at settlement) and the paid refund equals the supplied `refund_amount_cents`, capped such that `refund_amount_cents` does not exceed `paid_amount_cents` minus the existing `refund_total_cents`. Any excess is rejected with `ERR_REFUND_EXCEEDS_PAID`. This refund requires the slot to be `COMPLETED`; otherwise `ERR_REFUND_REQUIRES_COMPLETED_SESSION`. After the refund is applied, the booking's `refund_total_cents` is incremented by the sum of the deposit refund and the paid refund (in the post-completion case, only the paid component contributes), the slot's `net_revenue_cents` is decremented by `refund_amount_cents`, and an `AuditLogEntry` with action `BOOKING_REFUNDED` is emitted. If a `SettlementRun` in `FINALIZED` status already covers the slot, the run is automatically flipped to `REVERSED` — no error is raised — and its payout fields are recomputed proportionally per §3.10, with an `AuditLogEntry` of action `SETTLEMENT_REVERSED` written.

### 3.7. Match Quorum, Match Deadline, and Waitlist Promotion

The match axis is governed by quorum: the slot's `confirmed_seat_count` (denoted `n`), the slot's `required_seats_for_launch` (denoted `R`), and the deadline `match_deadline_at` (which equals `starts_at` minus `MATCH_CUTOFF_MINUTES`, where `MATCH_CUTOFF_MINUTES` is 60 minutes). Two distinct evaluation regimes apply.

When the current logical clock is strictly earlier than `match_deadline_at`, the match axis can flow freely between `OPEN` and `MATCHED`. If `match_status` is `OPEN` and `n` is at least `R`, the cascade advances the match axis to `MATCHED`. If `match_status` is `MATCHED` and `n` falls below `R` (because of cancellations), the cascade demotes the match axis back to `OPEN` — this demotion is permitted only while the clock is still earlier than `match_deadline_at`.

When the current logical clock is at or after `match_deadline_at`, evaluated only as part of a clock-advance scan, exactly one transition is allowed. If `match_status` is `OPEN`, the cascade flips it to `MATCH_FAILED` regardless of `n` (the slot's `OPEN` status at the deadline is decisive); the match-fail in turn cascades the schedule axis from `SCHEDULED` to `CANCELLED`, all bookings in `PENDING_DEPOSIT` or `CONFIRMED` to `CANCELLED` with `cancellation_initiator` of `SYSTEM_MATCH_FAIL` (full deposit and paid refunds), and all `QUEUED` waitlist entries to `EXPIRED`. If `match_status` is already `MATCHED` at the deadline, no change occurs — the match locks in pre-deadline, and later cancellations do not flip it back to `OPEN`; instead they trigger the slot-cancel cascade described in §3.3 only via the standard demotion path during the pre-deadline regime, with post-deadline cancellations demoting only via slot cancellation rather than match flip. The same scan also auto-cancels any `PROMOTED` booking whose `DEPOSIT_HOLD_TTL_MINUTES` (15 minutes from the promotion) has elapsed without a deposit confirmation; such auto-cancellations carry `cancellation_initiator` of `SYSTEM_MATCH_FAIL` (the encoding chosen for any system-driven non-player cancel), refund the held deposit fully (the booking was still in `PENDING_DEPOSIT`), and trigger another waitlist promotion sweep.

Players who arrive after the slot is full enqueue a `WaitlistEntry`. The body carries `requested_seat_count` (at least 1 and at most the theme's `max_players`); the server pins `priority_class` from the player's `tier` at enqueue time (`VIP` if `Player.tier` is `VIP`, otherwise `STANDARD`) and stamps `enqueued_at`. The waitlist entry begins in `QUEUED`. A player may cancel their own waitlist entry — the entry advances to `CANCELLED` (no refund applies since no deposit was held); an attempt by anyone other than the entry's `lead_player_id` is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. A waitlist entry advances to `EXPIRED` when its slot is cancelled or its slot's match axis flips to `MATCH_FAILED`.

Promotion runs immediately after any booking cancellation that frees seats. Let `freed_seats` equal the number of seats released and let the candidate set `E` be the slot's waitlist entries in `QUEUED`. Each candidate `e` is eligible if `e.requested_seat_count` is at most `freed_seats` (or, more precisely, at most the slot's remaining capacity after the cancellation). Within the eligible set, candidates are ordered first by priority class (entries whose `priority_class` is `VIP` precede those whose class is `STANDARD`), then by `enqueued_at` ascending (FIFO within a single priority class). When two entries share both `priority_class` and `enqueued_at` to the millisecond, the tie is broken by lexicographic ascending order of `entry.id`. The first ranked eligible entry is the winner: its status is set to `PROMOTED` and a fresh `Booking` row is created in `PENDING_DEPOSIT`, with `seat_count` equal to the winner's `requested_seat_count` and `lead_player_id` copied from the winner. The promoted player has `DEPOSIT_HOLD_TTL_MINUTES` (15 minutes from the promotion) to confirm the deposit; otherwise the new booking is auto-cancelled in the next clock-advance scan (per the previous paragraph) and another promotion sweep follows. The remaining capacity is reduced by the winner's seat count, and the sweep repeats over the remaining queued entries until no eligible entry remains. If the candidate set is empty or no entry qualifies, the sweep is a no-op and the cancellation still completes.

### 3.8. Staff Scheduling, Qualifications, Weekly Caps, and Handover

A `PlatformAdmin` registers a `StaffMember` with `chain_id`, `display_name`, a non-empty `roles_held` subset of `{HOST, NPC}`, a `qualifications` tag set (such as `DM_CERT` or `HORROR_SAFE`), an optional `max_weekly_minutes` (defaulting to 2400, bounded strictly greater than 0 and at most 10080 — the maximum minutes in a week), and an optional `commission_bps_override` that, when non-null, supersedes the venue's `host_commission_bps` for this staff member's `HOST` shifts. Staff members are contracted to a single chain; their `status` is `ACTIVE`, `ON_LEAVE`, or `TERMINATED`.

A `VenueOperator` creates a `StaffAssignment` by supplying `slot_id`, `staff_member_id`, and `role_type` (`HOST` or `NPC`). The server pins `assignment_minutes` as the slot's duration in minutes — the difference between the slot's `ends_at` and `starts_at`. The assignment begins in `SCHEDULED`. Five validations run in priority order. The staff member's `chain_id` must equal the slot's venue's `chain_id` (otherwise `ERR_STAFF_CHAIN_MISMATCH`). The proposed assignment must not collide with any other in-status assignment for the same staff member, where in-status means `SCHEDULED` or `ACTIVE` only — `HANDED_OFF`, `COMPLETED`, and `CANCELLED` assignments do not block (otherwise `ERR_STAFF_OVERLAP_CONFLICT`). Qualifications must match: for a `HOST` role, the staff member's `qualifications` must contain every entry of the theme's `required_host_qualifications`; for an `NPC` role, the staff member's `roles_held` must include `NPC` and the slot's theme must require at least the proposed NPC count (otherwise `ERR_STAFF_QUALIFICATION_MISMATCH`). Weekly minutes must remain within budget. The system computes the ISO week containing the assignment's slot start (Monday through Sunday in the chain's representative venue timezone — specifically the first venue in the chain by `created_at` ascending) and sums the `assignment_minutes` of the staff member's existing `SCHEDULED`, `ACTIVE`, or `COMPLETED` assignments in that same ISO week, excluding the proposed assignment itself. `HANDED_OFF` and `CANCELLED` assignments are excluded; the original assignment whose status is `HANDED_OFF` does not count, because its substitute already does. If the existing minutes plus the proposed minutes exceeds the staff member's `max_weekly_minutes`, the request is rejected with `ERR_STAFF_WEEKLY_LIMIT_EXCEEDED`.

When a staff member becomes unavailable before a slot starts, a venue operator may hand off the assignment to a substitute by supplying `substitute_staff_member_id`. The original assignment moves from `SCHEDULED` to `HANDED_OFF` and a new `StaffAssignment` row is created in `SCHEDULED` with `substitute_of_assignment_id` set to the original assignment's id. Three preconditions guard the handoff. The original assignment's own `substitute_of_assignment_id` must be null — substitution depth is capped at 1; chained substitutions are rejected with `ERR_SUBSTITUTE_DEPTH_EXCEEDED`. The slot must still be in `schedule_status` of `SCHEDULED`; once it is `LIVE`, handoff is rejected with `ERR_HANDOFF_AFTER_LIVE`. The substitute must satisfy the same qualification, weekly-minutes, and overlap rules as a fresh assignment — failing any of those returns the appropriate code from the original-assignment validation chain (`ERR_STAFF_QUALIFICATION_MISMATCH`, `ERR_STAFF_WEEKLY_LIMIT_EXCEEDED`, or `ERR_STAFF_OVERLAP_CONFLICT`). Subsequently, the cascading lifecycle of a `StaffAssignment` is driven by the slot: a `SCHEDULED` assignment cascades to `ACTIVE` on slot start, an `ACTIVE` assignment cascades to `COMPLETED` on slot complete, and a `SCHEDULED` assignment cascades to `CANCELLED` on slot cancel.

### 3.9. Reviews — Submission, Spam Scoring, Moderation, and Aggregation

A `Player` submits a review against one of their own `SETTLED` bookings, providing `theme_score` (1 through 5), an optional `host_score` (which may be null when no `HOST` `StaffAssignment` was completed for the slot, otherwise 1 through 5), `venue_score` (1 through 5), and `comment` (free text up to 2000 characters). The booking must be in `SETTLED` (otherwise `ERR_REVIEW_NOT_ELIGIBLE`) and the player must not have a prior review for the same booking (otherwise `ERR_REVIEW_DUPLICATE`); `author_player_id` is set to the booking's `lead_player_id`. The review enters `PENDING_MODERATION` with `moderation_round` initialised to 0, and an `AuditLogEntry` of action `REVIEW_SUBMITTED` is written.

At submission and at every resubmit, the server computes `spam_signal_count` in five fixed steps. The starting count is zero. Step 1: if the comment's length is below `SHORT_COMMENT_THRESHOLD` (50 characters), increment the count by 1. Step 2: count the reviews authored by the same `author_player_id` in the trailing 24 hours referencing the same `theme_id`; if that count is at or above `REPEAT_REVIEW_THRESHOLD` (3), increment by 1. Step 3: if the difference between the maximum and the minimum of `theme_score` and `venue_score` is at or above `SCORE_SPREAD_THRESHOLD` (3), increment by 1. Step 4: if the author has at least one prior `REJECTED` review whose `moderation_round` is at or above 1 — evaluated against the snapshot taken at the start of this calculation, deliberately excluding the review currently being submitted — increment by 1. Step 5: if this is a resubmission and `moderation_round` is greater than 0, increment by 1. The final value is `spam_signal_count`. Auto-routing applies: if `spam_signal_count` is at or above `SPAM_SIGNAL_HARD_BLOCK` (4), the review is auto-set to `REJECTED` immediately, with no moderator action required and an `AuditLogEntry` of action `REVIEW_REJECTED`; if it is at or above `SPAM_SIGNAL_SOFT` (2) but below the hard block, the review enters `PENDING_MODERATION` with a priority flag that affects only moderation queue ordering; otherwise the review enters `PENDING_MODERATION` normally. Step ordering is fixed because Step 4 reads a snapshot taken before Step 1 begins; reordering would change the snapshot and therefore the final count.

A `ContentModerator` resolves a `PENDING_MODERATION` review by issuing a `decision` of `APPROVE`, `REJECT`, or `HIDE`. An `APPROVE` decision moves the review to `PUBLISHED`, recomputes the relevant theme aggregates, and emits an `AuditLogEntry` of action `REVIEW_PUBLISHED`. A `REJECT` decision moves the review to `REJECTED` and emits an `AuditLogEntry` of action `REVIEW_REJECTED`. A `HIDE` decision is only valid against a `PUBLISHED` review and moves it to `HIDDEN`, removing it from theme aggregates going forward and emitting an `AuditLogEntry` of action `REVIEW_HIDDEN`. The author may revise a `REJECTED` review by patching `comment`, `theme_score`, `host_score`, or `venue_score`; the request requires `X-User-ID` to equal `author_player_id` (otherwise `ERR_INSUFFICIENT_PERMISSIONS`) and `moderation_round` to be strictly less than `MAX_MODERATION_ROUNDS` (3) — otherwise `ERR_REVIEW_REVISION_LIMIT`. On revise, `moderation_round` is incremented by 1 and the review moves to `REVISED`. Resubmitting moves the review from `REVISED` back to `PENDING_MODERATION`, requires the same author identity check, and recomputes `spam_signal_count` against the new content.

Per-theme aggregate scores are computed in a pinned order on every transition that touches `PUBLISHED` or `HIDDEN`. For each theme `T` and each dimension among `theme_score`, `host_score`, and `venue_score`, the source set is the set of reviews where the booking's slot's theme equals `T`, the review's `status` is `PUBLISHED`, and the dimension's score is not null (`HIDDEN`, `PENDING_MODERATION`, `REJECTED`, and `REVISED` reviews are excluded). The dimension's count is the size of the source set; when the count is zero, the aggregate is null. Otherwise, the system sums the integer scores in the source set, divides the sum by the count, multiplies by 10, applies round-half-up to the nearest integer, and divides by 10 — yielding a value to one decimal place. The pinned order is sum-then-divide-then-round; the alternative of rounding each review's contribution to one decimal first and then averaging produces a different number whenever the count is not a power of 2 and is therefore forbidden.

### 3.10. Settlement Runs and Reversal

A `PlatformAdmin` initiates a settlement by creating a `SettlementRun` with `chain_id`, `period_starts_at`, and `period_ends_at` (the latter strictly greater than the former). At creation, the server freezes `included_session_ids` to those `SessionSlot` rows whose `schedule_status` is `COMPLETED` and whose `ends_at` falls within the closed-open period bound by `period_starts_at` and `period_ends_at`. The freeze is performed once at sweep time and the list is pinned thereafter. With the included list fixed, the per-session allocation runs.

For each included session `S`, the per-session net is `max(0, S.net_revenue_cents)` — never negative. The author basis points for `S` is `S.theme.author_royalty_bps_override` if that field is non-null, otherwise the venue's `author_royalty_bps`. The host basis points for `S` is selected as follows: among the `HOST` `StaffAssignment` rows for `S` that are in `COMPLETED`, the system picks the assignment whose substitution chain ends at `COMPLETED`, ordered by `assignment.created_at` ascending, taking the first; this anchors the tie-break when both an original and its substitute exist. If that selected assignment's staff member has a non-null `commission_bps_override`, the host basis points is that override; otherwise it is the venue's `host_commission_bps`. If no completed `HOST` assignment exists for `S`, the host basis points is 0 — the host's share for that session redistributes into the platform tier. The venue basis points for `S` is the residual `max(0, 10000 minus the author bps minus the host bps minus the venue's platform_fee_bps)`. If the residual would be 0 because the sum of the author bps, the host bps, and the platform fee bps strictly exceeds 10000, the run is rejected with `ERR_REVENUE_SPLIT_INVALID`. NPC roles are not paid commission directly — they are paid as flat venue payroll out of the venue share.

The per-session allocation then splits the per-session net across the four tiers, flooring each share independently. The author share for `S` is the floor of `net_S` multiplied by the author bps divided by 10000. The host share for `S` is the floor of `net_S` multiplied by the host bps divided by 10000. The venue share for `S` is the floor of `net_S` multiplied by the venue bps divided by 10000. The platform share for `S` is `net_S` minus the sum of the other three — by construction, this absorbs the per-session rounding residue and is non-negative.

Run-level totals are then the sum of the per-session pieces. The `gross_total_cents` equals the sum of `net_revenue_cents` over the included sessions (note: by name "gross", this field aggregates the per-session **net** — that is, post-refund — revenue, because settlement is net of refunds, not gross). The `author_payout_cents`, `host_payout_cents`, `venue_payout_cents`, and `platform_fee_cents` are the sums of the per-session author, host, venue, and platform pieces respectively. The pinned arithmetic is **floor-then-sum**, never sum-then-floor: at one thousand sessions, the difference can amount to several hundred dropped cents. The pinned residue recipient is the platform tier — rounding residue does not flow back to the venue. The invariant `gross_total_cents` equals `author_payout_cents` plus `host_payout_cents` plus `venue_payout_cents` plus `platform_fee_cents` is enforced after the sums.

Finalising a run requires every included session to have `schedule_status` of `COMPLETED` (otherwise `ERR_SETTLEMENT_HAS_OPEN_SESSIONS`) and the per-venue bps sum `revenue_share_bps` plus `author_royalty_bps` plus `host_commission_bps` plus `platform_fee_bps` to equal exactly 10000 for every venue covered (otherwise `ERR_REVENUE_SPLIT_INVALID`). The payout fields are pinned and the run advances to `FINALIZED`, with an `AuditLogEntry` of action `SETTLEMENT_FINALIZED`. A finalised run is reversed automatically — moving from `FINALIZED` to `REVERSED` — when any booking under any included session transitions from `SETTLED` to `REFUNDED`; on reversal, all payout fields are recomputed using the post-refund `net_revenue_cents` and an `AuditLogEntry` of action `SETTLEMENT_REVERSED` is emitted. The system raises `ERR_SETTLEMENT_CHAIN_MISMATCH` defensively if a sweep ever surfaces a session whose venue's `chain_id` does not match the run's `chain_id`; in correct sweeps this never occurs.

### 3.11. Audit Log Access

Audit entries are queryable only by `PlatformAdmin`. The query accepts optional filters on `subject_entity_type`, `subject_entity_id`, and `actor_user_id`, and supports the standard pagination parameters. Results are returned in `created_at` ascending order, like every other list endpoint. The `payload_snapshot` field returns the full pre/post snapshot captured at the moment of action; the audit log is append-only and tamper-evidence in v1 rests solely on that property.

## 4. Endpoint Definitions

The following endpoints constitute the public API surface. Unless noted otherwise, creation endpoints (those that mint a new resource) return HTTP 201, and modification endpoints (state transitions, patches, cancellations) return HTTP 200. List and get endpoints return HTTP 200. Refer back to §3 for request body shapes, response cascades, and side effects; this table is intentionally minimal.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/venues` | Create venue | PlatformAdmin |
| GET | `/venues` | List venues | PlatformAdmin, VenueOperator, Player |
| GET | `/venues/{venueId}` | Get venue | PlatformAdmin, VenueOperator, Player |
| PATCH | `/venues/{venueId}` | Update venue (revenue split, hours, deposit policy) | PlatformAdmin |
| POST | `/venues/{venueId}/suspend` | Suspend venue | PlatformAdmin |
| POST | `/venues/{venueId}/resume` | Resume venue | PlatformAdmin |
| POST | `/venues/{venueId}/close` | Close venue (terminal) | PlatformAdmin |
| POST | `/venues/{venueId}/rooms` | Create room | VenueOperator |
| GET | `/venues/{venueId}/rooms` | List rooms in venue | PlatformAdmin, VenueOperator, Player |
| GET | `/venues/{venueId}/rooms/{roomId}` | Get room | PlatformAdmin, VenueOperator, Player |
| POST | `/venues/{venueId}/rooms/{roomId}/maintenance-windows` | Create maintenance window | VenueOperator |
| GET | `/venues/{venueId}/rooms/{roomId}/maintenance-windows` | List maintenance windows on room | PlatformAdmin, VenueOperator, Player |
| POST | `/themes` | Create theme (DRAFT) | ScriptAuthor |
| POST | `/themes/{themeId}/publish` | Publish theme | ScriptAuthor |
| POST | `/themes/{themeId}/publish-revision` | Publish a revised version (bumps current_version) | ScriptAuthor |
| POST | `/themes/{themeId}/retire` | Retire theme | ScriptAuthor |
| GET | `/themes/{themeId}` | Get theme | PlatformAdmin, VenueOperator, ScriptAuthor, Player |
| GET | `/themes` | List themes | PlatformAdmin, VenueOperator, ScriptAuthor, Player |
| POST | `/venues/{venueId}/rooms/{roomId}/session-slots` | Create session slot | VenueOperator |
| GET | `/venues/{venueId}/rooms/{roomId}/session-slots` | List slots on room | PlatformAdmin, VenueOperator, Player |
| GET | `/session-slots/{slotId}` | Get slot | PlatformAdmin, VenueOperator, Player |
| POST | `/session-slots/{slotId}/start` | Start session (LIVE) | VenueOperator |
| POST | `/session-slots/{slotId}/complete` | Complete session | VenueOperator |
| POST | `/session-slots/{slotId}/cancel` | Operator-cancel a session | VenueOperator |
| POST | `/session-slots/{slotId}/bookings` | Create booking | Player |
| POST | `/bookings/{bookingId}/confirm-deposit` | Confirm deposit (idempotent on payment-system callback) | Player, PaymentGateway |
| POST | `/bookings/{bookingId}/cancel` | Cancel booking (player or operator) | Player, VenueOperator |
| POST | `/bookings/{bookingId}/check-in` | Check in players for live session | VenueOperator |
| POST | `/bookings/{bookingId}/refund` | Post-session refund | VenueOperator |
| GET | `/bookings/{bookingId}` | Get booking | Player, VenueOperator, PlatformAdmin |
| POST | `/session-slots/{slotId}/waitlist-entries` | Enqueue on waitlist | Player |
| POST | `/waitlist-entries/{entryId}/cancel` | Cancel waitlist entry | Player |
| GET | `/session-slots/{slotId}/waitlist-entries` | List waitlist for slot | Player, VenueOperator |
| POST | `/players` | Register player | Player, PlatformAdmin |
| GET | `/players/{playerId}` | Get player | Player, VenueOperator, PlatformAdmin |
| POST | `/staff-members` | Register staff member | PlatformAdmin |
| GET | `/staff-members/{staffId}` | Get staff member | PlatformAdmin, VenueOperator, Host, NPC |
| POST | `/staff-assignments` | Assign staff to a slot | VenueOperator |
| POST | `/staff-assignments/{assignmentId}/handoff` | Hand off to substitute | VenueOperator |
| GET | `/staff-assignments/{assignmentId}` | Get staff assignment | VenueOperator, Host, NPC, PlatformAdmin |
| POST | `/bookings/{bookingId}/reviews` | Submit review | Player |
| PATCH | `/reviews/{reviewId}` | Revise rejected review | Player |
| POST | `/reviews/{reviewId}/resubmit` | Resubmit revised review | Player |
| POST | `/reviews/{reviewId}/moderate` | Moderate (APPROVE \| REJECT \| HIDE) | ContentModerator |
| GET | `/reviews/{reviewId}` | Get review | Player, ContentModerator, PlatformAdmin |
| POST | `/settlement-runs` | Create draft run (sweeps included sessions) | PlatformAdmin |
| POST | `/settlement-runs/{runId}/finalize` | Finalize run | PlatformAdmin |
| GET | `/settlement-runs/{runId}` | Get run | PlatformAdmin |
| GET | `/audit-log` | Query audit log | PlatformAdmin |
| POST | `/_clock/advance` | Advance the server clock; triggers time-gated cascades | PlatformAdmin |
| POST | `/_events/payment-confirmed` | Inbound payment-system event: simulate gateway confirming deposit hold | PaymentGateway, PlatformAdmin |
| POST | `/_events/script-authorization-revoked` | Inbound content-system event: theme version authorization revoked | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_OUTSIDE_START_WINDOW` | 409 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_THEME_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_WAITLIST_ENTRY_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 |
| `ERR_STAFF_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_RUN_NOT_FOUND` | 404 |
| `ERR_PLAYER_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_ACTIVE` | 409 |
| `ERR_VENUE_HAS_OPEN_SESSIONS` | 409 |
| `ERR_THEME_NOT_PUBLISHED` | 409 |
| `ERR_THEME_HAS_FUTURE_SESSIONS` | 409 |
| `ERR_SESSION_NOT_OPEN_FOR_CONFIRM` | 409 |
| `ERR_SESSION_NOT_OPEN_FOR_CANCEL` | 409 |
| `ERR_SESSION_NOT_LIVE` | 409 |
| `ERR_SESSION_NOT_MATCHED` | 409 |
| `ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER` | 409 |
| `ERR_REFUND_REQUIRES_COMPLETED_SESSION` | 409 |
| `ERR_REVIEW_REVISION_LIMIT` | 409 |
| `ERR_HANDOFF_AFTER_LIVE` | 409 |
| `ERR_SETTLEMENT_HAS_OPEN_SESSIONS` | 409 |
| `ERR_SETTLEMENT_ALREADY_FINALIZED` | 409 |
| `ERR_REVIEW_ALREADY_MODERATED` | 409 |
| `ERR_WAITLIST_ALREADY_PROMOTED` | 409 |
| `ERR_STAFF_OVERLAP_CONFLICT` | 409 |
| `ERR_SLOT_OVERLAP_CONFLICT` | 409 |
| `ERR_MAINTENANCE_OVERLAP_CONFLICT` | 409 |
| `ERR_SLOT_FULL` | 409 |
| `ERR_PLAYER_BANNED` | 403 |
| `ERR_MATCH_PREFERENCE_REJECTED` | 422 |
| `ERR_THEME_ROOM_INCOMPATIBLE` | 422 |
| `ERR_STAFF_CHAIN_MISMATCH` | 422 |
| `ERR_SETTLEMENT_CHAIN_MISMATCH` | 422 |
| `ERR_THEME_NO_COMPATIBLE_ROOM` | 422 |
| `ERR_STAFF_QUALIFICATION_MISMATCH` | 422 |
| `ERR_STAFF_WEEKLY_LIMIT_EXCEEDED` | 422 |
| `ERR_SUBSTITUTE_DEPTH_EXCEEDED` | 422 |
| `ERR_REVIEW_NOT_ELIGIBLE` | 422 |
| `ERR_REVIEW_DUPLICATE` | 422 |
| `ERR_REVENUE_SPLIT_INVALID` | 422 |
| `ERR_REFUND_EXCEEDS_PAID` | 422 |
| `ERR_STAFFING_INCOMPLETE` | 409 |
