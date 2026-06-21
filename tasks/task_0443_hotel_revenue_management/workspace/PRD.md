# Hotel Revenue Management API — Product Requirements Document

## 1. Introduction

Hotels live and die by how well they price a perishable, fixed-capacity asset: a room-night that goes unsold tonight can never be recovered. This document specifies the Hotel Revenue Management System (RMS), an API that lets a property's commercial team forecast demand, set and publish rates under length-of-stay and rate-class controls, govern overbooking within disciplined oversell limits, weigh group business against the transient revenue it would displace, and keep distribution channels in price parity — all while continuously surfacing the occupancy, ADR, and RevPAR figures that the business steers by.

The system is built around a flat collection of cooperating resources. A **Property** anchors physical capacity and the oversell ceiling; **RoomTypes** subdivide that capacity; **RatePlans** carry the commercial offer (rate class, length-of-stay band, base/floor/ceiling rates); **InventoryDays** track sold and available rooms for each individual night; **RateDecisions** drive nightly pricing through a publish workflow that applies yield rules and last-room-value premiums; **YieldRules** encode the occupancy breakpoints at which rates flex; **GroupBlocks** model the negotiate-evaluate-commit lifecycle of group business; **ChannelMappings** push rates to distribution channels and police parity; **CompetitorRates** record rate-shop snapshots of the competitive set; and **TransientReservations** capture individual bookings that consume inventory. Because rate publishing, group commits, and reservation confirmations all mutate shared nightly inventory and ripple outward into channel rates and property KPIs, the system places a premium on deterministic cascade ordering, precise rounding, and optimistic concurrency control so that two managers acting on the same plan or room type cannot silently clobber one another's work.

This API is consumed by four distinct operational roles whose responsibilities are deliberately separated: a revenue manager who owns pricing and yield strategy, a group sales manager who owns the group-block book, a channel manager who owns distribution and parity, and a read-only analyst who consumes forecasts and KPIs.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they act. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `RevenueManager`, `GroupSalesManager`, `ChannelManager`, and `Analyst`. The `RevenueManager` owns rate strategy — properties, room types, rate plans, inventory days, yield rules, rate decisions, group-displacement evaluation, and competitor-rate entry. The `GroupSalesManager` owns the group-block lifecycle — creating, revising, committing, and cancelling blocks. The `ChannelManager` owns distribution — channel mappings, parity, and competitor-rate entry. The `Analyst` is a read-only consumer of KPIs, forecasts, yield rules, decisions, and blocks.

All four roles carry an **opaque** identity. When `X-User-Role` is `RevenueManager`, `GroupSalesManager`, `ChannelManager`, or `Analyst`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`; authorization is decided purely by the role named in `X-User-Role`, never by matching `X-User-ID` against a resource owner.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by the resource's creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system share a common system-managed core. Every resource carries an `id`, a server-minted UUID used purely for identity and bearing no type prefix. Every resource also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when it was first created.

Resources that are mutable additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation — including mutations that arrive as a side effect of a cascade rather than a direct write — and a `version`, an integer that begins at 1 and increases by exactly 1 on each mutation. This `version` is the basis for optimistic concurrency control (§2.10). These mutable resources are `Property`, `RoomType`, `RatePlan`, `InventoryDay`, `RateDecision`, `YieldRule`, `GroupBlock`, `ChannelMapping`, and `TransientReservation`. The single exception is `CompetitorRate`: a rate-shop snapshot is immutable once recorded, so it carries only `id` and `created_at` — it has neither `updated_at` nor `version`.

The system runs on a **logical clock** rather than wall-clock time. The server's startup default is `2026-01-01T00:00:00Z`; before any clock-setting call the clock reads exactly this default and never falls back to the host's real time. A test-driving capability lets any of the four roles advance the clock by supplying a `to_iso8601` instant. Two computations read this clock directly: the days-to-arrival used in pickup forecasting and the "current date" used when computing property KPIs.

### 2.5. Hierarchical Consistency, Cascades, and Versioning

This is a flat system — resources reference one another by foreign keys carried in request bodies (`property_id`, `room_type_id`, `rate_plan_id`), never by nested URL paths — but several operations still produce ordered, multi-hop cascades that mutate more than one resource. Whenever a cascade touches a resource, that resource's `updated_at` is refreshed and, where the resource is mutable, its `version` is incremented by 1, exactly as for a direct write. The two largest cascades are publishing a rate decision and committing or cancelling a group block; both are specified in full in §3, but the governing principle is that every resource the cascade mutates participates in the same versioning and timestamping discipline as a directly written resource.

For requests that name a resource by `id` in the URL, the system first confirms that the addressed resource exists before applying any business rule, rejecting an unknown `id` with `ERR_NOT_FOUND`. For write requests that carry foreign keys in the body, the system confirms those references resolve to existing resources in the same property scope; an unresolvable or cross-property `property_id`, `room_type_id`, or `rate_plan_id` is rejected with `ERR_FK_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

All monetary and ratio outputs are produced with fixed precision using the round-half-up convention. Nightly rates and revenue figures — including a rate decision's `yielded_rate`, a channel's `channel_rate`, a group block's `displacement_cost`, and the `adr` and `revpar` KPIs — are rounded to exactly 2 decimal places. The `occupancy_pct` KPI and the `forecast_occupancy_pct` forecast output are rounded to exactly 4 decimal places. Room counts (`rooms_sold`, `rooms_available`, `group_held_rooms`, `transient_sold_rooms`, a forecast's `forecast_final_sold`, and oversell ceilings) are whole integers; wherever a ceiling is computed from a fractional product it is taken with the floor operation (the largest integer not exceeding the value). Any division whose denominator is zero yields 0 rather than an error.

### 2.7. The Oversell Ceiling and Availability Discipline

Capacity in this system is governed at the property level by an oversell allowance and enforced night by night. A property's `overbooking_limit_pct` expresses, as a fraction of capacity, how far the property may sell beyond its physical rooms — for example, 0.10 permits selling up to 110% of capacity. This fraction must be at least 0 and at most 0.30, and it defaults to 0.0 (no oversell) when omitted. For any given night, the oversell ceiling is the night's `physical_capacity` multiplied by the quantity one plus the property's `overbooking_limit_pct`, with the result floored to a whole number of rooms.

A night's availability is derived, never stored as authoritative: the rooms sold for the night equal the confirmed transient rooms plus the rooms held by committed groups, and the rooms still available equal the oversell ceiling minus the rooms sold, but never less than zero. No operation may push the rooms sold for any affected night above that night's oversell ceiling; an operation that would breach the ceiling on any night it touches is rejected with `ERR_OVERSELL_LIMIT_EXCEEDED`.

### 2.8. Rate-Class, Length-of-Stay, and Parity Governance

Each room type's rate plans are differentiated by `rate_class`, one of `BAR`, `CORPORATE`, `ADVANCE_PURCHASE`, or `PACKAGE`. Exactly one plan per room type may be designated the master BAR plan (`is_master_bar` true); this single plan drives the derived and parity rates pushed to distribution channels. Distribution channels are themselves enumerated as `DIRECT`, `OTA_A`, `OTA_B`, and `GDS`, and a channel's parity state (`parity_status`) is either `IN_PARITY` or `OUT_OF_PARITY`. Length-of-stay control is expressed per plan through `min_los` and `max_los`; the precise stay-length checks and their enforcement points are described in §3.

### 2.9. Validation Ordering and Precedence

When several checks could apply to a single request, the system evaluates them in a fixed precedence so that the returned error is deterministic. Authentication is evaluated first: a missing or unknown user context yields `ERR_UNAUTHENTICATED`. Authorization is evaluated next: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Existence of any resource named by `id` in the URL is checked third, yielding `ERR_NOT_FOUND`. Request-body well-formedness is checked fourth — required fields present, enums drawn from their permitted sets, numeric ranges respected (a plan's `ceiling_rate` at least its `floor_rate`, a property's `overbooking_limit_pct` within its band, counts at least 1) — yielding `ERR_INVALID_REQUEST` on failure. Foreign keys in the body are then resolved, yielding `ERR_FK_NOT_FOUND`. Only after these structural gates pass does the system apply the domain-specific business rules (uniqueness, state legality, fiscal floors, length-of-stay, inventory availability, evaluation prerequisites, and concurrency) described throughout §3. Within those business rules, where one operation is guarded by several, the controlling order is: a target's state legality is established before inventory-dependent and concurrency checks for that same transition.

### 2.10. Optimistic Concurrency Control

Two write operations guard against acting on a stale view of shared state by requiring the client to declare the parent version it last observed. These are the only two endpoints that take a version field; every other endpoint omits it.

Publishing a rate decision targets a rate plan as its concurrency parent. The publish request must carry `expected_rate_plan_version`, the `version` of the rate plan the client last read. If that value does not equal the rate plan's current `version` — which happens, for instance, when another writer has already published a decision for this plan, superseding the prior effective rate and bumping the plan's `version` — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting pricing it has not actually observed.

Committing a group block targets a room type as its concurrency parent. The commit request must carry `expected_room_type_version`, the `version` of the room type the client last read. If that value does not equal the room type's current `version` — which happens, for instance, when another group block was just committed on the same room type, consuming shared inventory and bumping the room type's `version` — the commit is rejected with `ERR_STALE_VERSION` (HTTP 412), so the committing client cannot act on an availability picture that no longer holds.

## 3. Business Logic & Workflows

### 3.1. Establishing the Property, Room Types, and Inventory

A `RevenueManager` stands up the property graph. A property is created with a `name`, a `total_rooms` count of all physically sellable rooms (which must be at least 1), an optional `overbooking_limit_pct` (defaulting to 0.0 and bounded as described in §2.7), and an optional `currency` ISO 4217 code that defaults to `USD` and governs every monetary field on the property. At creation the property's three KPI fields — `occupancy_pct`, `adr`, and `revpar` — are initialized to 0 and its `version` to 1.

Under a property, the same role defines room types. Each room type carries the `property_id` it belongs to, a short `code` unique within that property (for example `KING` or `DBLQ`), a display `name`, and a `physical_rooms` count of at least 1. If a second room type is created with a `code` already used inside the same property, the request is rejected with `ERR_DUPLICATE_ROOM_TYPE_CODE`.

Inventory is tracked one night at a time. An inventory day is created against a `room_type_id` for a particular `stay_date` (a night recorded at midnight UTC). Its `physical_capacity` of sellable rooms for that night is supplied optionally and defaults to the room type's `physical_rooms` when omitted; it must be at least 0. The night may be seeded with already-confirmed transient business through `transient_sold_rooms` (defaulting to 0) and `transient_revenue` (defaulting to 0), each of which must be at least 0. The system rejects a second inventory day for the same room type and stay date with `ERR_DUPLICATE_INVENTORY_DAY`. On creation, the night's `group_held_rooms` starts at 0, and its derived `rooms_sold` and `rooms_available` are computed immediately: rooms sold equal `transient_sold_rooms` plus `group_held_rooms`, and rooms available equal the oversell ceiling for the night minus rooms sold, floored at zero, where the ceiling is `physical_capacity` times one plus the property's `overbooking_limit_pct`, taken to the largest whole number not exceeding that product. A read of a single inventory day recomputes this availability before returning it.

A `RevenueManager` may later adjust a night directly. Updating an inventory day may change its `physical_capacity`, `transient_sold_rooms`, and `transient_revenue`; availability is recomputed afterward and the night's `version` increments by 1. Such an update may not push the night's rooms sold above its oversell ceiling, and a violating update is rejected with `ERR_OVERSELL_LIMIT_EXCEEDED`. The night's computed `id` and `room_type_id` identify it throughout.

### 3.2. Rate Plans and Their Closure

A `RevenueManager` attaches rate plans to a room type. A plan is created against its `room_type_id` with a `rate_class`, an optional `is_master_bar` flag (defaulting to false), an optional `min_los` length-of-stay minimum (defaulting to 1, at least 1), an optional `max_los` length-of-stay maximum (defaulting to 0, where 0 means unbounded and any positive value is at least 0), a `base_rate` (the list nightly rate before yield, at least 0), a `floor_rate` (the lowest rate yield rules may produce, at least 0), and a `ceiling_rate` (the highest rate yield rules may produce, which must be at least the `floor_rate`). A plan whose `max_los` is greater than 0 must also satisfy `max_los` being at least `min_los`; a plan that names a positive `max_los` smaller than its `min_los` is rejected with `ERR_INVALID_LOS_BAND`. At creation a plan's `status` is `ACTIVE`, its `published_rate` is null until the first publish sets it, and its `version` is 1. At most one plan per room type may carry `is_master_bar` true; a second master-BAR plan on the same room type is rejected with `ERR_MASTER_BAR_EXISTS`.

A plan's `status` lifecycle is a one-way gate from `ACTIVE` to `CLOSED`. Closing a plan is permitted only while it is `ACTIVE`; an attempt to close a plan that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. When a plan moves `ACTIVE → CLOSED`, every rate decision still in `DRAFT` on that plan is cascaded to `REJECTED` with its `reject_reason` set to "plan closed", and the closing plan's `version` increments by 1. A `CLOSED` plan accepts no new rate-decision creation and no publish.

### 3.3. Yield Rules and the Pickup Forecast

A `RevenueManager` defines yield rules at the property level. A yield rule carries the `property_id` it governs, a human-readable `name`, an `occupancy_threshold_pct` (the forecast occupancy at or above which the rule becomes eligible, expressed as a fraction at least 0 and at most 1), an `adjustment_pct` (a multiplicative rate adjustment — for example 0.15 raises the rate by 15% and -0.10 lowers it by 10%), a `priority` tie-break ordinal (an integer at least 1, where a lower value fires first), and an optional `enabled` flag defaulting to true. Only enabled rules are eligible at publish time.

The pickup forecast is an on-demand computed read over a single inventory night, projecting how many transient rooms will ultimately sell. It accepts a `method` query parameter selecting one of two variants, and group-held rooms are deliberately excluded — the forecast is transient-only. Under the default **SNAPSHOT_PACE** variant (selected when `method` is omitted or set to `SNAPSHOT_PACE`), the projected final sold count is the night's current `transient_sold_rooms` multiplied by a booking-curve pace factor of 1.5, with days-to-arrival ignored. Under the **TRAILING_PICKUP** variant (selected when `method` is `TRAILING_PICKUP`), the projection instead adds a fixed trailing daily pickup of 2 rooms for each remaining day before arrival, ignoring the pace factor; the remaining days are the number of whole days between the logical clock's current date and the `stay_date`, never less than zero. Whichever variant is used, the projected final sold count is then capped so it cannot exceed the night's oversell ceiling, and it is rounded half-up to a whole number. The forecast occupancy is the (capped, rounded) projected final sold count divided by the night's `physical_capacity`, rounded half-up to 4 decimal places — a value that may exceed 1.0 but only up to the oversell allowance. The forecast read returns `forecast_final_sold`, `forecast_occupancy_pct`, and the `method` used.

### 3.4. Drafting, Publishing, and Superseding Rate Decisions

The nightly price for a plan is set through a rate decision and its publish workflow. A `RevenueManager` creates a decision against a `rate_plan_id` for a given `stay_date`, supplying a `requested_rate` (the manager's proposed nightly rate before any yield clamping, at least 0). A decision is born in `DRAFT` with its `yielded_rate` null and its `version` 1. Creation is gated two ways: the underlying plan must be `ACTIVE`, and a create against a `CLOSED` plan is rejected with `ERR_PLAN_CLOSED`; and the `requested_rate` must be at least the plan's `floor_rate`, with a below-floor request rejected up front, before any yield computation, with `ERR_RATE_BELOW_FLOOR`.

Publishing a `DRAFT` decision (`DRAFT → PUBLISHED`) is the system's most consequential operation and is restricted to a `RevenueManager`. Before any pricing is computed, the publish is gated: the decision must be in `DRAFT` state, otherwise `ERR_INVALID_STATE`; the plan must be `ACTIVE`, otherwise `ERR_PLAN_CLOSED`; an inventory day must already exist for the decision's room type and `stay_date`, because yield reads its forecast occupancy, otherwise `ERR_MISSING_INVENTORY_DAY`; and the request's `expected_rate_plan_version` must match the plan's current `version`, otherwise `ERR_STALE_VERSION` as described in §2.10. State legality is established before the concurrency check.

When those gates pass, the system computes the decision's `yielded_rate` in a strictly pinned order. **First**, it establishes the forecast occupancy basis for the matching inventory day using the SNAPSHOT_PACE pickup forecast (the transient-only variant of §3.3). **Second**, it selects at most one yield rule: among the property's enabled rules whose `occupancy_threshold_pct` is less than or equal to that basis occupancy, it chooses the one with the highest `occupancy_threshold_pct`; ties are broken by the lower `priority` value, and any remaining tie by the earlier `created_at`. If a rule is chosen, the running rate becomes the `requested_rate` multiplied by the quantity one plus that rule's `adjustment_pct`; if no rule is eligible, the running rate stays equal to the `requested_rate`. **Third**, the last-room-value premium is considered: if the night's current `rooms_available` (per §2.7) is at or below 5 rooms, the running rate is multiplied by 1.20 (a 20% premium) and `last_room_premium_applied` is set true; otherwise no premium is applied. **Fourth**, the running rate is clamped into the plan's band — taken as no less than `floor_rate` and no more than `ceiling_rate`, with the floor applied first and the ceiling applied as the upper bound — and only then rounded half-up to 2 decimal places to yield the final `yielded_rate`. The premium is therefore applied before the clamp, and the clamp before the rounding; this order is fixed. The decision records the single `applied_yield_rule_id` that fired (or null if none), and its `last_room_premium_applied` flag.

A successful publish then runs an ordered three-hop cascade. The decision's `yielded_rate` becomes the plan's `published_rate`, and the plan's `version` increments by 1. **Hop 1:** any prior decision still `PUBLISHED` for the same plan and `stay_date` is moved `PUBLISHED → SUPERSEDED`, since it no longer drives the plan's `published_rate`. **Hop 2:** only when the published decision's plan is the room type's master BAR plan, every channel mapping under that plan re-syncs its `channel_rate` and recomputes its `parity_status` (the channel sync of §3.6). **Hop 3:** the property's KPI fields are recomputed (the property KPI of §3.8). Each resource touched by these hops refreshes its `updated_at` and, where mutable, bumps its `version`.

Rejecting a `DRAFT` decision (`DRAFT → REJECTED`), also a `RevenueManager` action, is the divergent branch. The request optionally supplies a `reject_reason`, which is stored. Rejection is allowed only from `DRAFT` (otherwise `ERR_INVALID_STATE`); the decision's `yielded_rate` stays null, the plan's `published_rate` is left unchanged, and there is no channel sync and no KPI recompute. Beyond these two manager actions, the only path into `SUPERSEDED` is the system-driven hop above: a previously `PUBLISHED` decision is moved to `SUPERSEDED` precisely when a newer decision for the same plan and `stay_date` reaches `PUBLISHED`. Each decision exposes its `id`, `rate_plan_id`, `stay_date`, and `status`, and decisions can be listed filtered by `rate_plan_id`, by `stay_date`, or by the computed `applied_yield_rule_id`.

### 3.5. Distribution Channels and Parity

A `ChannelManager` maps rate plans onto distribution channels. A mapping is created against a `rate_plan_id` for a particular `channel`, with an optional `markup_pct` (a multiplicative gross-up over the plan's published rate — for example 0.18 models an 18% commission gross-up; defaults to 0.0, at least 0) and an optional `manual_rate_override` (which when set replaces the synced rate to model a channel pricing off-strategy; defaults to null and, when set, must be at least 0). At most one mapping may exist per plan and channel; a duplicate is rejected with `ERR_CHANNEL_ALREADY_MAPPED`. On creation the channel's `channel_rate` is synced from the plan's published rate (or the override) if a rate is available, and its `parity_status` is computed; its `version` starts at 1. The same role may later update a mapping's `markup_pct` and/or `manual_rate_override`, which re-runs the sync, recomputes `parity_status`, and increments `version` by 1. Each mapping exposes its `id` and `rate_plan_id`, and mappings can be listed filtered by `rate_plan_id` and by `channel`.

### 3.6. Channel Sync and the Parity Band

Channel sync derives a channel's published rate and judges its parity against the direct channel. It runs whenever a master BAR decision is published (hop 2 of §3.4) and whenever a mapping is created or has its override or markup updated. A channel's `channel_rate` is its `manual_rate_override` when that override is set; otherwise it is the plan's `published_rate` multiplied by the quantity one plus the channel's `markup_pct`, rounded half-up to 2 decimal places. The channel's net (commission-stripped) rate is its `channel_rate` divided by the quantity one plus its `markup_pct`. Parity is judged against the `DIRECT` mapping of the same plan: the direct rate is the DIRECT mapping's own `manual_rate_override` when set, else the plan's `published_rate` times one plus the DIRECT mapping's `markup_pct`, rounded half-up to 2 decimal places, and the direct net rate is that direct rate divided by one plus the DIRECT mapping's `markup_pct`. A channel is judged `OUT_OF_PARITY` when its net rate is strictly less than the direct net rate reduced by a parity tolerance of 2% of the direct net rate (that is, less than the direct net rate multiplied by the quantity one minus 0.02); otherwise it is `IN_PARITY`. The `DIRECT` mapping is always its own parity reference and is therefore always `IN_PARITY`, and a purely synced channel carrying no override always nets back to the published rate and is likewise `IN_PARITY`.

### 3.7. The Group-Block Lifecycle and Displacement Analysis

A `GroupSalesManager` opens group business by creating a group block against a `room_type_id`, naming the requesting `group_name`, its `arrival_date`, the number of consecutive `nights` (at least 1), the `rooms_per_night` requested for every night (at least 1), and the per-room per-night `offered_rate` (at least 0). A block is born `NEGOTIATING` with its `displacement_cost` and `recommendation` null and its `version` 1. The block's lifecycle is a revision loop that precedes commitment: `NEGOTIATING` and `REVISION_REQUESTED` cycle back and forth before a block either commits or is lost.

Before any revision or commit, a `RevenueManager` runs displacement analysis on the block, which sets its `displacement_cost` and a `recommendation` of `ACCEPT` or `REJECT` and bumps the block's `version`. Evaluation requires an inventory day to exist for every night in the block's window (from `arrival_date` through the night before `arrival_date` plus `nights`); a missing night is rejected with `ERR_MISSING_INVENTORY_DAY`. The analysis accepts a `method` query parameter with two variants. In both, the total group rooms equal `rooms_per_night` times `nights`, and the group value equals the `offered_rate` times those total group rooms. The displaced revenue is summed across the block's nights, and for each night the system computes a spill — the transient rooms turned away by the group. For a night, the would-be transient demand is the SNAPSHOT_PACE projected final sold count for that night (per §3.3); the true capacity for displacement is the night's `physical_capacity` with no oversell applied, since displacement counts real rooms; the rooms that would have sold without this group equal the lesser of that demand and the capacity minus the group-held rooms already committed by other blocks (excluding this block); and the spill is the amount by which those would-be-sold rooms plus this block's `rooms_per_night` exceed the capacity, never less than zero. Under the default **LRV** variant (selected when `method` is omitted or `LRV`), each night's spill is valued at the room type's effective BAR rate — a last-room-value proxy that is the master BAR plan's `published_rate` if a master BAR plan exists and has been published, else that plan's `base_rate` if a master BAR plan exists but has not yet published, else 0 if the room type has no master BAR plan at all. Under the **FORECAST_REV** variant (selected when `method` is `FORECAST_REV`), each night's spill is instead valued at that night's realized transient ADR, which is the night's `transient_revenue` divided by its `transient_sold_rooms` (with the denominator treated as at least 1 to avoid division by zero). The `displacement_cost` is the summed displaced revenue rounded half-up to 2 decimal places, and the group value is likewise to 2 decimal places; the recommendation is `ACCEPT` when the group value is at least the displacement cost, and `REJECT` otherwise.

When an evaluation recommends `REJECT`, the `RevenueManager` may move the block `NEGOTIATING → REVISION_REQUESTED`, recording that a higher rate or smaller block is sought; this requires the block to be `NEGOTIATING` and to have been evaluated to a `REJECT` recommendation, and an unevaluated block (its `displacement_cost` still null) is rejected with `ERR_NOT_EVALUATED`. The `GroupSalesManager` then revises the block while it is `REVISION_REQUESTED`, supplying a new `offered_rate` and/or `rooms_per_night`; this moves it back `REVISION_REQUESTED → NEGOTIATING`, resets `displacement_cost` and `recommendation` to null so the block must be re-evaluated, and bumps `version`.

Committing a block (`NEGOTIATING → COMMITTED`) is a `GroupSalesManager` action that actually holds inventory. It is gated in order: the block must be `NEGOTIATING` (otherwise `ERR_INVALID_STATE`); it must have been evaluated with an `ACCEPT` recommendation (an unevaluated block yields `ERR_NOT_EVALUATED`); if the room type has a master BAR plan, the block's `nights` must satisfy that plan's length-of-stay band — at least its `min_los`, and where its `max_los` is positive at most that `max_los` — with a violation rejected as `ERR_LOS_VIOLATION`, while a room type with no master BAR plan imposes no length-of-stay constraint on the group; an inventory day must exist for every night in the window, otherwise `ERR_MISSING_INVENTORY_DAY`; the room type's current `version` must match the request's `expected_room_type_version`, otherwise `ERR_STALE_VERSION` (§2.10); and for every night the night's `rooms_available` after the oversell ceiling must be at least the block's `rooms_per_night`, otherwise the commit is rejected with `ERR_OVERSELL_LIMIT_EXCEEDED`. On a successful commit, each overlapping inventory day has its `group_held_rooms` increased by the block's `rooms_per_night` and its `rooms_sold` and `rooms_available` recomputed (cascade hop 1), the room type's `version` increments by 1, and the property KPIs are recomputed (cascade hop 2).

Cancelling a block is also a `GroupSalesManager` action and behaves by current state. A `COMMITTED` block goes `COMMITTED → CANCELLED`: each overlapping inventory day has its `group_held_rooms` decreased by the block's `rooms_per_night` — restoring exactly the rooms it held — with availability recomputed, and the property KPIs are recomputed. A block still `NEGOTIATING` or `REVISION_REQUESTED` goes instead to `LOST`: because no inventory was ever held in those states, no inventory day changes. Each block exposes its `id` and `room_type_id`, and blocks can be listed filtered by `room_type_id` and by `status`.

### 3.8. Property KPIs

Property KPIs measure the property's performance on the logical clock's current date. They are recomputed as a cascade hop after a rate decision is published (hop 3) and after a group block is committed or cancelled (hop 2), and they can also be recomputed on demand. The computation spans all inventory days across the property's room types whose `stay_date` equals the current logical date. The total available rooms are the sum of those nights' `physical_capacity`; the total rooms sold are the sum of those nights' `rooms_sold` (transient plus group-held); and the total room revenue is the sum of those nights' `transient_revenue` plus, for each committed group block covering the current date, that block's held rooms for the night times its `offered_rate`. From these, `occupancy_pct` is the total rooms sold divided by the total available rooms, rounded half-up to 4 decimal places; `adr` is the total room revenue divided by the total rooms sold, rounded half-up to 2 decimal places; and `revpar` is the total room revenue divided by the total available rooms, rounded half-up to 2 decimal places. Any of these whose denominator is zero is reported as 0.

### 3.9. Transient Reservations

A `RevenueManager` books individual (non-group) stays as transient reservations. A reservation is created against a `room_type_id` and the `rate_plan_id` whose length-of-stay control and published rate it will use, with an `arrival_date`, a count of consecutive `nights` (at least 1), and the `rooms` booked for every night of the stay (at least 1). A reservation is born `HELD` with its `booked_rate` null, its `version` 1, and no inventory consumed yet. At creation, the stay's `nights` is checked against the reservation's own plan's length-of-stay band — at least `min_los`, and where `max_los` is positive at most `max_los` — with a violation rejected as `ERR_LOS_VIOLATION`.

Confirming a `HELD` reservation (`HELD → CONFIRMED`) consumes inventory and is gated: the reservation must be `HELD` (otherwise `ERR_INVALID_STATE`); its plan must be `ACTIVE` and must already have a non-null published rate, since a confirm without a published rate is rejected with `ERR_RATE_NOT_PUBLISHED`; the stay's `nights` is re-checked against the plan's length-of-stay band, again `ERR_LOS_VIOLATION` on failure; an inventory day must exist for every night in the window (from `arrival_date` through the night before `arrival_date` plus `nights`), otherwise `ERR_MISSING_INVENTORY_DAY`; and for every night the night's `rooms_available` after the oversell ceiling must be at least the reservation's `rooms`, otherwise `ERR_OVERSELL_LIMIT_EXCEEDED`. On confirm, the reservation captures its `booked_rate` from the plan's current published rate; each overlapping inventory day has its `transient_sold_rooms` increased by the reservation's `rooms` and its `transient_revenue` increased by `rooms` times the captured `booked_rate`, with availability recomputed; and the property KPIs are recomputed.

Checking out a `CONFIRMED` reservation (`CONFIRMED → CHECKED_OUT`) realizes the stay and is allowed only from `CONFIRMED` (otherwise `ERR_INVALID_STATE`); the consumed transient counts are retained — there is no inventory release on checkout. Cancelling a reservation is permitted from either `HELD` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`) and moves it to `CANCELLED`. If the reservation was `CONFIRMED`, each overlapping inventory day has its `transient_sold_rooms` decreased by the reservation's `rooms` and its `transient_revenue` decreased by `rooms` times the captured `booked_rate` — restoring exactly the counts it consumed — availability is recomputed, and the property KPIs are recomputed; if it was merely `HELD`, no inventory was consumed and no inventory day changes. Each reservation exposes its `id`, `room_type_id`, and `rate_plan_id`, and reservations can be listed filtered by `room_type_id`, by `rate_plan_id`, and by `status`.

### 3.10. Competitor Rate Shopping

Either a `RevenueManager` or a `ChannelManager` records competitor rate-shop snapshots for the property. A snapshot names the `property_id` it belongs to, the `competitor_name` of the shopped compset hotel, the `stay_date` the shopped rate applies to, the `shopped_rate` observed (at least 0), and the `shopped_at` logical time the snapshot was taken. A snapshot is immutable once recorded: it carries only `id` and `created_at`, with no later mutation. Snapshots can be listed filtered by `property_id` and by `stay_date`, and a single snapshot can be retrieved by `id`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that read a resource, recompute a derived view, or drive a state transition or other modification return `200 OK`. All list endpoints accept the pagination query parameters `limit` and `offset`; collection list endpoints additionally accept the foreign-key and status filters noted in §3. The full request and response shape for each operation is reconstructed from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| POST | `/properties` | Create a property | RevenueManager |
| GET | `/properties/{id}` | Get a property with current KPI fields | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| GET | `/properties` | List properties | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| GET | `/properties/{id}/kpis` | Recompute and return property KPIs for the current logical date | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| POST | `/room-types` | Create a room type under a property | RevenueManager |
| GET | `/room-types/{id}` | Get a room type | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| GET | `/room-types` | List room types | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| POST | `/rate-plans` | Create a rate plan under a room type | RevenueManager |
| GET | `/rate-plans/{id}` | Get a rate plan | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| GET | `/rate-plans` | List rate plans | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| POST | `/rate-plans/{id}/close` | Close a rate plan | RevenueManager |
| POST | `/inventory-days` | Create an inventory day for a stay date | RevenueManager |
| GET | `/inventory-days/{id}` | Get an inventory day with computed availability | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| GET | `/inventory-days` | List inventory days | RevenueManager, GroupSalesManager, ChannelManager, Analyst |
| PATCH | `/inventory-days/{id}` | Update transient sold rooms, revenue, or capacity for a night | RevenueManager |
| GET | `/inventory-days/{id}/forecast` | Computed read: pickup/demand forecast for the night | RevenueManager, Analyst |
| POST | `/yield-rules` | Create a yield rule for the property | RevenueManager |
| GET | `/yield-rules/{id}` | Get a yield rule | RevenueManager, Analyst |
| GET | `/yield-rules` | List yield rules | RevenueManager, Analyst |
| POST | `/rate-decisions` | Create a DRAFT rate decision for a stay date | RevenueManager |
| GET | `/rate-decisions/{id}` | Get a rate decision | RevenueManager, ChannelManager, Analyst |
| GET | `/rate-decisions` | List rate decisions | RevenueManager, ChannelManager, Analyst |
| POST | `/rate-decisions/{id}/publish` | Publish a DRAFT rate decision (OCC on rate plan) | RevenueManager |
| POST | `/rate-decisions/{id}/reject` | Reject a DRAFT rate decision | RevenueManager |
| POST | `/channel-mappings` | Map a rate plan to a distribution channel | ChannelManager |
| GET | `/channel-mappings/{id}` | Get a channel mapping | ChannelManager, RevenueManager, Analyst |
| GET | `/channel-mappings` | List channel mappings | ChannelManager, RevenueManager, Analyst |
| PATCH | `/channel-mappings/{id}` | Update a mapping's markup or manual override; re-sync and recompute parity | ChannelManager |
| POST | `/group-blocks` | Create a group block request (NEGOTIATING) | GroupSalesManager |
| GET | `/group-blocks/{id}` | Get a group block | GroupSalesManager, RevenueManager, Analyst |
| GET | `/group-blocks` | List group blocks | GroupSalesManager, RevenueManager, Analyst |
| PATCH | `/group-blocks/{id}` | Revise a group block's offered rate and/or rooms per night | GroupSalesManager |
| POST | `/group-blocks/{id}/evaluate` | Run group-displacement analysis | RevenueManager |
| POST | `/group-blocks/{id}/request-revision` | Request a revision on a REJECT-evaluated block | RevenueManager |
| POST | `/group-blocks/{id}/commit` | Commit an ACCEPT-evaluated block, holding inventory (OCC on room type) | GroupSalesManager |
| POST | `/group-blocks/{id}/cancel` | Cancel a block (release inventory if committed; otherwise lose it) | GroupSalesManager |
| POST | `/competitor-rates` | Record a competitor rate-shop snapshot | RevenueManager, ChannelManager |
| GET | `/competitor-rates/{id}` | Get a competitor rate snapshot | RevenueManager, ChannelManager, Analyst |
| GET | `/competitor-rates` | List competitor rate snapshots | RevenueManager, ChannelManager, Analyst |
| POST | `/transient-reservations` | Create a transient reservation in HELD | RevenueManager |
| GET | `/transient-reservations/{id}` | Get a transient reservation | RevenueManager, Analyst |
| GET | `/transient-reservations` | List transient reservations | RevenueManager, Analyst |
| POST | `/transient-reservations/{id}/confirm` | Confirm a HELD reservation, consuming transient inventory | RevenueManager |
| POST | `/transient-reservations/{id}/check-out` | Check out a CONFIRMED reservation | RevenueManager |
| POST | `/transient-reservations/{id}/cancel` | Cancel a reservation (release inventory if confirmed) | RevenueManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_ROOM_TYPE_CODE` | 409 |
| `ERR_MASTER_BAR_EXISTS` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_CLOSED` | 409 |
| `ERR_LOS_VIOLATION` | 422 |
| `ERR_MISSING_INVENTORY_DAY` | 409 |
| `ERR_NOT_EVALUATED` | 409 |
| `ERR_OVERSELL_LIMIT_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RATE_NOT_PUBLISHED` | 409 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_DUPLICATE_INVENTORY_DAY` | 409 |
| `ERR_CHANNEL_ALREADY_MAPPED` | 409 |
| `ERR_INVALID_LOS_BAND` | 422 |
| `ERR_RATE_BELOW_FLOOR` | 422 |
