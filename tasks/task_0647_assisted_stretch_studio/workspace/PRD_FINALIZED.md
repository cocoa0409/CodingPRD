# Assisted Stretch Studio API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a multi-location recovery and assisted-stretch studio of the kind a member would recognize from a StretchLab-style brand. The studio sells one-on-one assisted-stretch and recovery sessions delivered by trained flexologists on dedicated stretch tables, and it monetizes those sessions through two parallel funding instruments: recurring memberships that grant a monthly bundle of credits, and prepaid credit packs purchased outright. A member's journey begins with a mandatory intro session and mobility assessment, after which they may purchase memberships, book sessions, attach recovery add-ons, and string sessions into recurring weekly series.

The hard part of this domain is not any single booking; it is keeping a member's credit wallet, a flexologist's calendar, a table's occupancy, and a member's standing all consistent as bookings are created, confirmed, completed, cancelled, frozen, and swept. Credits are held when a session is booked and only consumed when it is completed; a late cancellation or a no-show forfeits the held credit and accrues strike points that can suspend a member; freezing a membership must claw back the future sessions it was funding. Because several of these effects cascade two or three layers deep and several of them are time-sensitive, the system runs on an explicit logical clock rather than wall-clock time, and a number of state changes are driven by an operator-invoked sweep rather than by background timers.

This specification is written for the engineers who will implement that backend. It defines the resource model, the parallel state machines that govern bookings and memberships, the credit and fee arithmetic, the validation order, and the role-based access rules. Monetary amounts are expressed in integer cents throughout, and all time comparisons are performed in UTC against the logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The four roles are `Member`, `Flexologist`, `FrontDesk`, and `StudioManager`. When a recognized role attempts an operation it is not permitted to perform, or when an ownership check fails, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two of the roles are tied to persisted entities and two are opaque operator identities, and the distinction governs how ownership is enforced:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare the resource's `member_id` (or, for the member record itself, its `id`) to `X-User-ID`; a member may act only on their own memberships, credit packs, bookings, series, add-ons, and no-show events.
- When `X-User-Role` is `Flexologist`, `X-User-ID` is the `id` of the acting `Flexologist`. A flexologist may read and complete only those bookings whose `flexologist_id` equals `X-User-ID`, and may read their own flexologist record; ownership checks compare the booking's `flexologist_id` to `X-User-ID`.
- When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A front-desk operator books, cancels, reschedules, and registers on behalf of members; the server does not compare `X-User-ID` to any entity's `id`.
- When `X-User-Role` is `StudioManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A studio manager administers the catalog, runs operational sweeps, sets the clock, and reinstates members; the server does not compare `X-User-ID` to any entity's `id`.

A `StudioManager` is a superset operator: in addition to its exclusive catalog, ops, clock, reinstatement, and renewal capabilities, it may perform any booking, membership, credit-pack, series, or read operation otherwise available to members or the front desk. A `FrontDesk` operator may act for any member; a `Member` may act only for themselves. Catalog reads (locations, flexologists, tables, services) are available to all four roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0. A `limit` or `offset` that is non-integer, below its minimum, or above its maximum is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Identity, Timestamps, and Common Resource Properties

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at creation and increments by one on every mutation; it underpins optimistic concurrency control (§2.7).

The following resources carry the full common set (`id`, `created_at`, `updated_at`, `version`): `Location`, `Flexologist`, `Table`, `Service`, `Member`, `Membership`, `CreditPack`, `Booking`, and `RecurringSeries`. Three resources are leaner: `AddOn`, `NoShowEvent`, and `ClockState` carry only `id` and `created_at` — they have no `updated_at` and no `version` field, and those fields must be absent from their representations.

### 2.5. Nested Path Resolution and Reference Integrity

The topology is flat: bookings, members, memberships, credit packs, recurring series, flexologists, tables, services, and locations are all root-level collections linked by foreign-key fields rather than nested under one another in the URL. A handful of endpoints do expose a sub-resource under a parent identifier — a booking's add-ons, a booking's no-show events, and a member's no-show events. For any path that contains an identifier, the system validates identifiers left to right: a path id that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any deeper lookup or body validation runs. The same `ERR_NOT_FOUND` covers any foreign key supplied in a request body that does not resolve — `member_id`, `location_id`, `service_id`, `flexologist_id`, `table_id`, `funding_id`, `booking_id`, and the rest — again checked left to right.

### 2.6. Credit Wallets and the Reconciliation Principle

A funding wallet is either a `Membership` or a `CreditPack`, and each wallet exposes the same four derived credit fields, reconciled synchronously on every event that touches the wallet: `granted_credits`, `held_credits`, `consumed_credits`, and `available_credits`. These are never free-standing counters that drift; they are recomputed from the bookings the wallet funds, in a pinned order so that the derivation never reads a value it is still computing. First, `held_credits` is the sum of `credit_cost` across every booking whose `funding_id` is this wallet and whose `credit_status` is `HELD`. Second, `consumed_credits` is the sum of `credit_cost` across every booking funded by this wallet whose `credit_status` is either `CONSUMED` or `FORFEITED`. Third, `granted_credits` is, for a membership, the credits granted into the wallet this cycle (`included_credits` plus any rollover carried in on renewal), and for a credit pack, simply its `pack_credits`. Fourth, `available_credits` is `granted_credits` minus `held_credits` minus `consumed_credits`, floored at zero so it is never negative.

A booking hold is admitted only when, evaluated in this order, the wallet's `available_credits` is at least the booking's `credit_cost`. When that is not true the booking is rejected with `ERR_INSUFFICIENT_CREDITS` (HTTP 409). All credit quantities are whole integers; there is no fractional credit and no rounding within the wallet.

### 2.7. Optimistic Concurrency Control on Memberships

Three membership lifecycle operations — freeze, unfreeze, and cancel — are guarded by optimistic concurrency control on the membership's `version`. Each of these requests must carry `expected_membership_version`, a non-optional field that states the `version` the client last observed for the target `Membership`. If `expected_membership_version` does not equal the membership's current `version`, the request is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412), and no state change occurs.

Consider freezing a membership. If another writer has, since the client last read the membership, already frozen, unfrozen, or cancelled it — each of which legitimately advances the `version` and reshapes the wallet — then the client's `expected_membership_version` is stale and the freeze is refused on the stale-version check rather than acting on an out-of-date view of the wallet and freeze history. Cancellation is governed identically: a cancel that carries a stale `expected_membership_version` would supersede the prior membership state while acting on an obsolete view, so it is refused with `ERR_STALE_MEMBERSHIP_VERSION`. No other endpoint takes a version field; only freeze, unfreeze, and cancel participate in this check.

### 2.8. The Logical Clock and Operational Sweeps

The system keeps a single logical clock, persisted as the `ClockState` singleton's `current_utc`. At server startup this reads exactly `2026-04-01T00:00:00Z`, and it never falls back to wall-clock time; before the clock is explicitly set, every time comparison uses that default. Only an explicit set-clock operation moves the clock, assigning `current_utc` to the supplied `to_iso8601` instant. Setting the clock performs no automatic sweeps — time-driven consequences are realized only when an operator runs the no-show sweep.

The no-show sweep is the system's deferred-action engine. When invoked (optionally scoped to a single `location_id`), it performs three passes. Any `CONFIRMED` booking whose `session_end_utc` is at or before the clock is marked `NO_SHOW` (see §3.5). Any `ACTIVE` or `DEPLETED` credit pack whose `expires_utc` is at or before the clock transitions to `EXPIRED`, after which its remaining `available_credits` are permanently unusable, although holds already placed survive. Finally, every affected member's `strike_score` is recomputed with rolling-window decay and their `status` flips between `SUSPENDED` and `ACTIVE` at the threshold (see §3.7).

### 2.9. Monetary and Time Precision

All monetary fields are integer cents: `monthly_fee_cents`, `no_show_fee_cents`, `list_price_cents`, `base_unit_price_cents`, `price_cents`, `fee_charged_cents`, and `freeze_credit_cents`. Where a calculation produces a fractional cent intermediate, the result is rounded to whole cents using the round-half-up method; the precise point at which rounding is applied is specified per calculation in §3 and matters because rounding before versus after a later addition can change the result. The `late_cancel_pct` is a fraction between 0 and 1. Time fields are ISO 8601 UTC instants; all session, freeze, expiry, and window comparisons are performed in UTC against the logical clock. Each location's open and close are expressed as `open_minute_of_day` and `close_minute_of_day`, minutes after midnight UTC.

### 2.10. Cascading State and Version Semantics

Several operations mutate more than one resource in a single atomic request, and every secondary effect is reconciled synchronously before the response returns. When a membership is frozen, unfrozen, cancelled, or renewed, its own `version` increments and its `updated_at` refreshes; the same holds for any booking whose status the operation flips, and for any wallet whose derived credit fields are recomputed as a consequence. A booking that is cancelled by a cascade has its `schedule_status` and `credit_status` changed, its `updated_at` refreshed, its `version` incremented, and any non-voided `AddOn` attached to it marked `voided`. These cascades can run two or three layers deep — for example, a no-show forfeits a credit, creates a `NoShowEvent`, recomputes the member's `strike_score`, and may suspend the member — and each layer independently mutates and re-versions the resource it touches. The exact triggers and the entities each cascade reaches are described in §3.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Locations, Flexologists, Tables, and Services

The catalog is the bedrock every booking stands on, and only a `StudioManager` may author it. A location is created with a display `name` and optional configuration: an IANA `timezone` (informational only — default `UTC` — because all logical-clock comparisons run in UTC), an `open_minute_of_day` (default 540, i.e., 09:00 UTC, inclusive) and a `close_minute_of_day` (default 1260, i.e., 21:00 UTC, exclusive) where the open minute must be strictly less than the close minute and the close minute may be at most 1440, a `flexologist_buffer_minutes` (default 15, at least 0) that sets the mandatory gap between consecutive sessions for the same provider, a `no_show_fee_cents` (default 5000, at least 0) flat penalty, a `late_cancel_pct` (default 0.50, between 0 and 1) used to prorate late-cancel fees, and a `cancel_window_hours` (default 12, at least 0) that divides free cancellations from late ones. A location's `status` begins `OPEN`; closing it transitions `status` to `CLOSED`, after which new bookings at that location are blocked.

A flexologist record carries a home `location_id`, a `full_name`, and a `certified_intro` flag (default false) marking whether they may run intro mobility assessments; `status` begins `ACTIVE` and deactivation moves it to `INACTIVE`, after which the flexologist cannot be assigned to new bookings. A table carries a `location_id` and a human `label` such as "Table 3 / Room B"; its `status` begins `ACTIVE` and taking it out of service moves it to `OUT_OF_SERVICE`, after which it cannot accept new bookings. A service carries a `location_id`, a `name`, a `kind` of `ASSISTED_STRETCH`, `RECOVERY`, or `INTRO`, a `duration_minutes` greater than zero, a `credit_cost` of at least zero, and a `list_price_cents` of at least zero that is the basis for late-cancel proration; its `status` begins `ACTIVE` and retiring it moves it to `RETIRED`, after which it cannot be booked. The `INTRO` kind is the one-time intro session and mobility assessment. Catalog list endpoints accept filters — locations by `status`; flexologists, tables, and services by `location_id` and `status` (services additionally by `kind`) — to support reverse lookup from a location to the records that reference it.

### 3.2. Member Onboarding and the Intro Gate

A member is registered by a `StudioManager` or `FrontDesk` operator with a `home_location_id`, a `full_name`, and an `email`. At registration the member's `status` is `ACTIVE`, `intro_completed` is false, `mobility_tier` is null, and `strike_score` is 0. The member's own `id` equals `X-User-ID` whenever they act as a `Member`. The members list may be filtered by `home_location_id` and `status`.

A pivotal rule governs what a fresh member may book. While `intro_completed` is false, the member may book only a service whose `kind` is `INTRO`; any attempt to book a non-intro service before the intro is completed is rejected with `ERR_INTRO_REQUIRED` (HTTP 409). The `intro_completed` flag flips to true only when an `INTRO` booking for that member reaches `COMPLETED`, at which point the mobility assessment posted at completion also sets `mobility_tier` (see §3.4). The `intro_completed` flag is what gates membership purchase, and `mobility_tier` is the read-only assessment outcome — one of `FOUNDATION`, `INTERMEDIATE`, `ADVANCED`, or null until the intro completes. A member's `is_intro` flag on a booking is computed true exactly when the booked service's `kind` is `INTRO`.

### 3.3. Booking a Session: Creation, Holds, and the Gauntlet of Checks

Creating a booking is the most heavily validated operation in the system. The request supplies `member_id`, `location_id`, `service_id`, `flexologist_id`, `table_id`, `session_start_utc`, `funding_source`, and `funding_id`. On success the booking is born with `schedule_status` `REQUESTED` and `credit_status` `HELD`; its `session_end_utc` is computed as `session_start_utc` plus the service's `duration_minutes`; its `credit_cost` and `list_price_cents` are snapshotted from the service at create time so later catalog edits cannot retroactively change a booking; `is_intro` is set; and a hold for `credit_cost` is placed against the funding wallet. The `funding_source` is `MEMBERSHIP` or `CREDIT_PACK`, and `funding_id` is polymorphic — it is a membership id when the source is `MEMBERSHIP` and a credit-pack id when the source is `CREDIT_PACK`. Two system fields, `series_id` and `rescheduled_from_booking_id`, default to null on a directly created booking and are populated only when the booking originates from a recurring series or a reschedule respectively.

The validations on booking creation run in a fixed priority order, and the ordering is load-bearing because the first failing check determines which error the caller sees. Authentication is checked first (`ERR_UNAUTHENTICATED`, 401), then role and ownership (`ERR_FORBIDDEN`, 403), then the existence of every referenced resource left to right (`ERR_NOT_FOUND`, 404). Next is cross-location integrity: the chosen service, flexologist, table, and funding wallet must all belong to the booking's `location_id`, and the `funding_id` type must agree with `funding_source`; any mismatch is `ERR_LOCATION_MISMATCH` (HTTP 422). After that the member's standing is checked — a `SUSPENDED` member cannot create or confirm bookings and is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409) — followed by the intro gate described in §3.2 (`ERR_INTRO_REQUIRED`, 409). Then come the temporal and resource checks described below, then certification, and finally the credit check (`ERR_INSUFFICIENT_CREDITS`, 409) from §2.6. A booking at a `CLOSED` location is rejected with `ERR_LOCATION_CLOSED` (HTTP 409).

The temporal feasibility check requires that `session_start_utc` be strictly later than the clock, that it fall within the location's open and close minutes, and that the referenced service, flexologist, and table all be in their bookable state at the correct location; a violation is `ERR_OUTSIDE_BUSINESS_HOURS` (HTTP 422), which also covers a `RETIRED` service, an `INACTIVE` flexologist, or an `OUT_OF_SERVICE` table. Table availability is then checked on a half-open interval from start to end: no other non-terminal booking on the same `table_id` may overlap that interval, though exact adjacency, where one session's end equals the next session's start, is allowed; a conflict is `ERR_TABLE_UNAVAILABLE` (HTTP 409). Flexologist availability uses a different geometry: a new session conflicts when its start is strictly earlier than a prior non-terminal session's end plus the location's `flexologist_buffer_minutes`, meaning the gap between consecutive sessions for the same `flexologist_id` must be at least the buffer; a conflict is `ERR_FLEXOLOGIST_UNAVAILABLE` (HTTP 409). Finally, an `INTRO` booking requires the assigned flexologist's `certified_intro` to be true; otherwise the booking is rejected with `ERR_FLEXOLOGIST_NOT_CERTIFIED` (HTTP 422). The credit pack used as a funding source must additionally not be `EXPIRED`, and the booking's `session_start_utc` must be strictly earlier than the pack's `expires_utc`; otherwise the credit check fails with `ERR_INSUFFICIENT_CREDITS`.

Bookings can be filtered on the list endpoint by `member_id`, `location_id`, `service_id`, `flexologist_id`, `table_id`, `series_id`, `rescheduled_from_booking_id`, `funding_id`, `schedule_status`, and `credit_status`.

### 3.4. The Booking Lifecycle: Confirm, Complete, and the Assessment

A booking carries two independent status dimensions that live on the same row and evolve under their own triggers: `schedule_status`, which tracks the scheduling lifecycle, and `credit_status`, which tracks the wallet. The scheduling dimension starts `REQUESTED` and may advance to `CONFIRMED`, then to `COMPLETED`, with `CANCELLED`, `LATE_CANCELLED`, and `NO_SHOW` as the alternative terminal outcomes. The credit dimension starts `HELD` and resolves to `CONSUMED`, `RELEASED`, or `FORFEITED`.

Confirming a requested booking is permitted only when its `schedule_status` is `REQUESTED`, the member's `status` is `ACTIVE` (a `SUSPENDED` member is blocked with `ERR_MEMBER_SUSPENDED`), and the location's `status` is `OPEN`; on success `schedule_status` advances `REQUESTED → CONFIRMED`. Completing a booking is permitted only when its `schedule_status` is `CONFIRMED`, the clock has reached or passed `session_start_utc`, and `credit_status` is still `HELD`. On completion `schedule_status` advances `CONFIRMED → COMPLETED` and the credit dimension advances `HELD → CONSUMED`, which means the funding wallet's `held_credits` decreases by the booking's `credit_cost` and its `consumed_credits` increases by the same amount. Attempting any transition from a status that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409).

Completing an `INTRO` booking does double duty. The completion request may carry four assessment sub-scores — `assessment_shoulder`, `assessment_hip`, `assessment_spine`, and `assessment_ankle`, each from 0 to 100. On completing an intro booking the system flips the member's `intro_completed` to true and computes the member's `mobility_tier` from a weighted composite of those four sub-scores. The composite multiplies the shoulder sub-score by 0.30, the hip sub-score by 0.30, the spine sub-score by 0.25, and the ankle sub-score by 0.15 (weights that sum to one), sums the four products in exact decimal, and then rounds half-up exactly once to an integer composite. A composite of at least 80 yields `ADVANCED`; otherwise a composite of at least 60 yields `INTERMEDIATE`; otherwise the tier is `FOUNDATION`. Completion of a booking is a `Flexologist` (acting on a booking assigned to self) or `StudioManager` action.

### 3.5. Cancellations, No-Shows, Fees, and Add-Ons

Cancelling a booking resolves to one of two outcomes determined entirely by where the clock sits relative to the cancellation window, and the boundary is exact. Let the window edge be `session_start_utc` minus the location's `cancel_window_hours`. If the clock is at or before that edge, the cancellation is free: `schedule_status` becomes `CANCELLED`, the credit dimension moves `HELD → RELEASED` (the held credit returns to the wallet's available pool as `held_credits` decreases by `credit_cost`), `fee_charged_cents` stays 0, and any non-voided add-ons are voided. If the clock is strictly after that edge but strictly before `session_start_utc`, the cancellation is late: `schedule_status` becomes `LATE_CANCELLED`, the credit dimension moves `HELD → FORFEITED` (the credit is lost rather than returned — `held_credits` decreases by `credit_cost` and `consumed_credits` increases by `credit_cost`), and a fee is charged. Cancellation is permitted only while `schedule_status` is `REQUESTED` or `CONFIRMED`; otherwise it is rejected with `ERR_INVALID_STATE`.

A no-show is detected only by the sweep (§2.8): a booking still `CONFIRMED` when the clock has reached or passed its `session_end_utc` is marked `NO_SHOW`, its credit dimension moves `HELD → FORFEITED` exactly as in a late cancel, a fee is charged, and its add-ons are voided.

The fee depends on which terminal the booking reached. On a no-show the fee written to `fee_charged_cents` is the flat `no_show_fee_cents` configured on the location, independent of the service price. On a late cancellation the fee is the booking's snapshotted `list_price_cents` multiplied by the location's `late_cancel_pct`, rounded half-up to whole cents — so the late-cancel fee scales with the booked service price while the no-show fee does not. Both a late cancellation and a no-show also create a `NoShowEvent` (see §3.7), which in turn recomputes the member's `strike_score` and may suspend the member; this is a depth-three cascade that completes synchronously within the originating request.

A member, front-desk operator, or manager may attach a recovery add-on to a booking, supplying its `kind` (`COMPRESSION` or `PERCUSSION`) and its `price_cents` captured at attach time. An add-on may be attached only while the booking's `schedule_status` is `REQUESTED` or `CONFIRMED`; attaching to a booking in any other state is rejected with `ERR_ADDON_NOT_ALLOWED` (HTTP 409). An `AddOn` is created with `voided` false; whenever its parent booking is cancelled, late-cancelled, or no-showed — directly or by cascade — every non-voided add-on on that booking is set to `voided` true. Each `AddOn` references its parent through `booking_id`, and the add-ons of a booking can be listed.

Rescheduling a non-terminal booking is a cancel-and-recreate. The request supplies a new `session_start_utc` and optionally a new `flexologist_id` and `table_id`. The predecessor booking is cancelled free of charge — `schedule_status` to `CANCELLED`, credit `HELD → RELEASED`, add-ons voided — and a fresh booking is created in `REQUESTED`/`HELD` with `rescheduled_from_booking_id` set to the predecessor's `id`. The replacement re-runs the full overlap and credit gauntlet of §3.3 and re-holds the credit; if any check fails, the replacement is rejected and the predecessor is not disturbed.

### 3.6. No-Show Events, Strike Decay, and Suspension

Every late cancellation and every no-show is recorded as a `NoShowEvent` carrying the member's `member_id`, the `booking_id` that resolved, an `event_kind` of `LATE_CANCEL` or `NO_SHOW`, a `points` value, and the `occurred_utc` instant taken from the logical clock. A `NO_SHOW` event is worth 2 `points`; a `LATE_CANCEL` event is worth 1 point. A member's no-show events can be listed, and a booking's no-show events can be listed.

A member's `strike_score` is a rolling-window sum, not a lifetime tally. It is recomputed whenever a `NoShowEvent` is created and whenever the sweep runs: the window opens 90 days before the current clock instant, and the score is the sum of `points` over that member's events whose `occurred_utc` is at or after the window start. Events older than 90 days drop out of the sum entirely — a step decay rather than a gradual one. When the recomputed `strike_score` reaches 5 or more, the member's `status` is set to `SUSPENDED`; when it is strictly below 5, the member is `ACTIVE` and is reinstated automatically on the next recompute. A `SUSPENDED` member cannot create or confirm bookings or activate series. A `StudioManager` may also manually reinstate a suspended member, moving `status` from `SUSPENDED` back to `ACTIVE`; this override does not erase the underlying no-show events, so `strike_score` will be recomputed from those same events on the next event creation or sweep.

### 3.7. Memberships: Purchase, Freeze, Unfreeze, Cancel, and Renewal

A membership is purchased with a `member_id`, a `location_id`, a `tier` of `STARTER`, `PLUS`, or `PRO`, a `monthly_fee_cents`, an `included_credits` grant, and an optional `rollover_cap` (default 0) that caps how many unused membership-granted credits carry into the next cycle on renewal. Purchase is allowed only if the member's `intro_completed` is true, and a member may hold at most one membership in `ACTIVE` or `FROZEN` status per location; violating either rule is rejected with `ERR_MEMBERSHIP_NOT_ALLOWED` (HTTP 409). On creation the membership's `status` is `ACTIVE`, `granted_credits` equals `included_credits`, `held_credits` and `consumed_credits` are 0, `cycle_anchor_utc` is set to the current clock, `freeze_credit_cents` is 0, and `version` is 1. Memberships can be filtered by `member_id`, `location_id`, and `status`.

A membership's `status` cycles between `ACTIVE` and `FROZEN` any number of times before it reaches the terminal `CANCELLED`. Freezing requires that the membership currently be `ACTIVE`, that the supplied `freeze_end_utc` be later than the current clock, and that `expected_membership_version` match the membership's `version` (§2.7, else `ERR_STALE_MEMBERSHIP_VERSION`, 412). The freeze request supplies `freeze_start_utc`, `freeze_end_utc`, and `expected_membership_version`. On a successful freeze the `status` moves `ACTIVE → FROZEN`, the `version` increments by one, and a fee credit is accrued into `freeze_credit_cents`. That credit is computed by first taking the number of frozen days as the ceiling, to a whole number of days, of the span from `freeze_start_utc` to `freeze_end_utc`, then multiplying the `monthly_fee_cents` by those frozen days, dividing by a fixed denominator of 30 days in exact decimal, and rounding half-up once to whole cents; each freeze in a cycle adds its credit to the running `freeze_credit_cents`. The denominator is always 30 regardless of the actual length of the billing cycle.

Freezing also cascades into the calendar. Every `CONFIRMED` or `REQUESTED` booking funded by this membership whose `session_start_utc` falls within the half-open span from `freeze_start_utc` up to `freeze_end_utc` is cancelled: its `schedule_status` becomes `CANCELLED`, its `credit_status` moves `HELD → RELEASED`, and its add-ons are voided. Each released booking's credit flip recomputes the membership wallet transitively. Unfreezing requires the membership be `FROZEN` and that `expected_membership_version` match; it moves `status` `FROZEN → ACTIVE` and increments `version`. Cancelling a membership requires it be `ACTIVE` or `FROZEN` and that `expected_membership_version` match; it moves `status` to `CANCELLED`, increments `version`, and cascades so that all `HELD` bookings funded by this membership are cancelled with their credit released and their add-ons voided. A transition attempted from a status that does not allow it is rejected with `ERR_INVALID_STATE`.

Renewing a membership advances it to its next billing cycle and is a `StudioManager` action. On renewal the carried-over credits are the smaller of the wallet's current `available_credits` and the `rollover_cap`, and `granted_credits` becomes `included_credits` plus that carried amount; `consumed_credits` resets to 0 while `held_credits` is left unchanged so that open holds persist; `cycle_anchor_utc` advances by 30 days; `freeze_credit_cents` resets to 0; and `version` increments by one. Any unused credits beyond the rollover cap simply expire.

### 3.8. Credit Packs: Tiered Pricing and Expiry

A credit pack is purchased with a `member_id`, a `location_id`, a `pack_credits` count greater than zero, a `base_unit_price_cents` per-credit list price, and an `expires_utc` instant. The total `price_cents` is computed at purchase with a volume discount applied in a strictly pinned order. First, a subtotal is formed by multiplying `base_unit_price_cents` by `pack_credits`. Then a discount fraction is chosen by pack size: 0.15 when `pack_credits` is at least 20, otherwise 0.10 when it is at least 10, otherwise 0.05 when it is at least 5, otherwise 0.00. The discounted subtotal is the subtotal multiplied by one minus that discount fraction, and this discounted subtotal is rounded half-up to whole cents at this step — before anything else is added. Finally, a flat processing fee of 300 cents is added to the rounded discounted subtotal to produce `price_cents`. The order matters: the discount is applied, then the result is rounded, then the flat fee is added.

On creation the pack's `status` is `ACTIVE`, its `held_credits` and `consumed_credits` are 0, and its `available_credits` equals `pack_credits`. A pack's wallet behaves exactly as §2.6 specifies, with `granted_credits` equal to `pack_credits`. A pack's `status` informally drops to `DEPLETED` the moment its `available_credits` reaches 0 after a hold or consume, and returns to `ACTIVE` when a booking it funded is released and `available_credits` rises above 0 again — depletion is informational and a pack remains usable once credits free up. When the sweep finds an `ACTIVE` or `DEPLETED` pack whose `expires_utc` is at or before the clock, it sets `status` to `EXPIRED`, a terminal state; the remaining `available_credits` then become permanently unusable, though any holds already placed keep their hold. Credit packs can be filtered by `member_id`, `location_id`, and `status`.

### 3.9. Recurring Series: Draft, Activation, and the Materialization Waterfall

A recurring series lets a member pre-book a cadence of identical sessions. A draft series is created with a `member_id`, a `location_id`, a `service_id`, a `flexologist_id`, a `table_id`, a `funding_source`, a `funding_id`, a `first_start_utc`, an `interval_days` greater than zero, and an `occurrence_count` between 1 and 26; an `occurrence_count` outside that range or an `interval_days` of zero or less is rejected with `ERR_SERIES_OCCURRENCE_LIMIT` (HTTP 422). On creation `status` is `DRAFT`, with `generated_count` and `skipped_count` both 0. The cross-location integrity rule of §3.3 applies at series creation and at activation: the service, flexologist, table, and funding wallet must all belong to the series' `location_id`, else `ERR_LOCATION_MISMATCH`. Series can be filtered by `member_id`, `location_id`, `service_id`, `flexologist_id`, `table_id`, `funding_id`, and `status`.

Activating a series requires that its `status` be `DRAFT` and that the funding wallet referenced by `funding_id` exist and be usable — a membership that is `ACTIVE` (not `FROZEN` or `CANCELLED`) or a credit pack that is `ACTIVE` (not `EXPIRED`). Activation materializes bookings in a waterfall evaluated occurrence by occurrence in strict chronological order, with the occurrence index running from 0 upward, never by id. For each occurrence k, the prospective start is `first_start_utc` plus k times `interval_days`. If that occurrence would collide on its `table_id`, collide on its `flexologist_id`, or find the funding wallet's `available_credits` below the service's `credit_cost`, the occurrence is skipped and the waterfall continues to the next occurrence; it is not a failure of the whole activation. Otherwise a booking is created in `HELD` and the service's `credit_cost` is held from the wallet, so earlier occurrences consume credits before later ones get their turn. After the pass, `generated_count` holds the number of bookings actually created, `skipped_count` holds the number skipped, the `status` moves `DRAFT → ACTIVE`, and each generated booking carries this series' id in its `series_id`. A `SUSPENDED` member cannot activate a series (`ERR_MEMBER_SUSPENDED`).

Cancelling an active series ends it: `status` moves `ACTIVE → ENDED`, and every future booking generated by this series — those whose `session_start_utc` is strictly after the clock and whose `credit_status` is still `HELD` — is cancelled, with `schedule_status` set to `CANCELLED`, credit moved `HELD → RELEASED`, and add-ons voided. A series transition attempted from a state that does not allow it is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource, and list and read operations, return `200 OK`. The no-show sweep returns `200 OK` with an empty data object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/locations` | Create a studio location | StudioManager |
| GET | `/locations` | List locations | StudioManager, FrontDesk, Member, Flexologist |
| GET | `/locations/{id}` | Get a location | StudioManager, FrontDesk, Member, Flexologist |
| POST | `/locations/{id}/close` | Close a location to new bookings | StudioManager |
| POST | `/flexologists` | Create a flexologist | StudioManager |
| GET | `/flexologists` | List/filter flexologists | StudioManager, FrontDesk, Member |
| GET | `/flexologists/{id}` | Get a flexologist | StudioManager, FrontDesk, Member, Flexologist |
| POST | `/flexologists/{id}/deactivate` | Mark a flexologist INACTIVE | StudioManager |
| POST | `/tables` | Create a stretch table/room | StudioManager |
| GET | `/tables` | List/filter tables | StudioManager, FrontDesk, Member |
| GET | `/tables/{id}` | Get a table | StudioManager, FrontDesk, Member, Flexologist |
| POST | `/tables/{id}/take-out-of-service` | Mark a table OUT_OF_SERVICE | StudioManager |
| POST | `/services` | Create a service in a location's catalog | StudioManager |
| GET | `/services` | List/filter services | StudioManager, FrontDesk, Member |
| GET | `/services/{id}` | Get a service | StudioManager, FrontDesk, Member, Flexologist |
| POST | `/services/{id}/retire` | Retire a service | StudioManager |
| POST | `/members` | Register a member | StudioManager, FrontDesk |
| GET | `/members` | List/filter members | StudioManager, FrontDesk |
| GET | `/members/{id}` | Get a member | StudioManager, FrontDesk, Member |
| POST | `/members/{id}/reinstate` | Manually reinstate a suspended member | StudioManager |
| GET | `/members/{id}/no-show-events` | List a member's no-show/late-cancel events | StudioManager, FrontDesk, Member |
| POST | `/memberships` | Purchase a membership | StudioManager, FrontDesk, Member |
| GET | `/memberships` | List/filter memberships | StudioManager, FrontDesk, Member |
| GET | `/memberships/{id}` | Get a membership | StudioManager, FrontDesk, Member |
| POST | `/memberships/{id}/freeze` | Freeze a membership for a date span | StudioManager, Member |
| POST | `/memberships/{id}/unfreeze` | Unfreeze a frozen membership | StudioManager, Member |
| POST | `/memberships/{id}/cancel` | Cancel a membership | StudioManager, Member |
| POST | `/memberships/{id}/renew` | Advance a membership to its next cycle | StudioManager |
| POST | `/credit-packs` | Purchase a credit pack | StudioManager, FrontDesk, Member |
| GET | `/credit-packs` | List/filter credit packs | StudioManager, FrontDesk, Member |
| GET | `/credit-packs/{id}` | Get a credit pack | StudioManager, FrontDesk, Member |
| POST | `/bookings` | Create a booking | StudioManager, FrontDesk, Member |
| GET | `/bookings` | List/filter bookings | StudioManager, FrontDesk, Member, Flexologist |
| GET | `/bookings/{id}` | Get a booking | StudioManager, FrontDesk, Member, Flexologist |
| POST | `/bookings/{id}/confirm` | Confirm a requested booking | StudioManager, FrontDesk, Member |
| POST | `/bookings/{id}/complete` | Complete a confirmed booking | StudioManager, Flexologist |
| POST | `/bookings/{id}/cancel` | Cancel a booking | StudioManager, FrontDesk, Member |
| POST | `/bookings/{id}/reschedule` | Reschedule a non-terminal booking | StudioManager, FrontDesk, Member |
| POST | `/bookings/{id}/add-ons` | Attach an add-on to a booking | StudioManager, FrontDesk, Member |
| GET | `/bookings/{id}/add-ons` | List add-ons on a booking | StudioManager, FrontDesk, Member, Flexologist |
| GET | `/bookings/{id}/no-show-events` | List a booking's no-show/late-cancel events | StudioManager, FrontDesk, Member |
| POST | `/recurring-series` | Create a recurring series draft | StudioManager, FrontDesk, Member |
| GET | `/recurring-series` | List/filter recurring series | StudioManager, FrontDesk, Member |
| GET | `/recurring-series/{id}` | Get a recurring series | StudioManager, FrontDesk, Member |
| POST | `/recurring-series/{id}/activate` | Materialize the series into bookings | StudioManager, FrontDesk, Member |
| POST | `/recurring-series/{id}/cancel` | End a series and cancel its future bookings | StudioManager, FrontDesk, Member |
| POST | `/_clock/set_current_utc` | Set the logical clock | StudioManager |
| POST | `/_ops/no_show_sweep` | Run the no-show/expiry/strike sweep | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_LOCATION_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_MEMBERSHIP_VERSION` | 412 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_INTRO_REQUIRED` | 409 |
| `ERR_OUTSIDE_BUSINESS_HOURS` | 422 |
| `ERR_TABLE_UNAVAILABLE` | 409 |
| `ERR_FLEXOLOGIST_UNAVAILABLE` | 409 |
| `ERR_FLEXOLOGIST_NOT_CERTIFIED` | 422 |
| `ERR_INSUFFICIENT_CREDITS` | 409 |
| `ERR_MEMBERSHIP_NOT_ALLOWED` | 409 |
| `ERR_ADDON_NOT_ALLOWED` | 409 |
| `ERR_LOCATION_CLOSED` | 409 |
| `ERR_SERIES_OCCURRENCE_LIMIT` | 422 |
