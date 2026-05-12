# Hotel Revenue Management API — Product Requirements Document

## 1. Introduction

A modern hotel competes for revenue across many surfaces at once: physical inventory has to be allocated to several distribution channels, nightly rates have to react to demand without breaking parity contracts, overbooking has to balance opportunity against the very real cost of walking a guest, and every lifecycle event — from booking to check-out — has to settle cleanly across reservation, payment, housekeeping, and accounting boundaries. When any one of these surfaces drifts (a stale rate published on an OTA, a maintenance block that overlaps a confirmed booking, an overbooking policy that no longer matches forecast no-show probability), revenue leaks immediately and visibly.

This document specifies the Hotel Revenue Management API — the system of record that operations, revenue management, the front desk, housekeeping, and the guest-facing booking flow all converge on. The API governs the configuration of room types, rooms, channels, rate plans, and overbooking policies; the proposal and approval of rate overrides under segregation-of-duties; the inventory and overbooking gating that makes a confirmation legal; and the full reservation lifecycle through check-in, check-out, walk-out, no-show, cancellation, refund, and dispute. Every monetary outcome is reproducible from inputs, every state change is auditable, and every cross-channel side effect is explicit.

A key design point worth stating up front: the system distinguishes between **forward-looking estimates** used for planning (e.g., expected walkout cost given current confirmations and forecast no-show probability) and **realised outcomes** booked at moment of execution (e.g., the actual compensation a walked-out guest receives). The two will routinely produce different numbers for the same date and room type. Both are first-class.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (except the public `GET /_health` probe, if present) MUST carry two HTTP headers: `X-User-ID` and `X-User-Role`. A request that omits either header is rejected with `ERR_AUTH_MISSING` (HTTP 401). A request whose `X-User-Role` value is not authorized for the targeted endpoint per the RBAC matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognises exactly seven roles, spelled exactly as follows: `PlatformAdmin`, `RevenueAnalyst`, `RevenueManager`, `ReservationsAgent`, `FrontDeskClerk`, `HousekeepingStaff`, and `Guest`.

For every role, `X-User-ID` is treated as an **opaque operator identifier** that the server does not resolve against any persisted entity table — there is no user-account collection in this domain. The server may, however, **record** the identifier on entities where the scaffolded workflow demands it: in particular, when a `RevenueManager` approves a rate override, the server captures the supplied `X-User-ID` into `approved_by` on the affected `RateOverride`, and segregation-of-duties checks compare a fresh `X-User-ID` against that previously recorded value. No role's `X-User-ID` is otherwise compared to any entity `id`.

- A `PlatformAdmin` performs hotel-wide IT and operations administration: defining room types, registering physical rooms, registering distribution channels, resolving disputes, and driving the test logical clock.
- A `RevenueAnalyst` proposes rate overrides and may withdraw their own pending submissions. They are explicitly forbidden from approving any override they themselves submitted.
- A `RevenueManager` configures rate plans, channel-rate-plan mappings, and overbooking policies, and approves or rejects rate overrides proposed by analysts.
- A `ReservationsAgent` books, confirms, modifies, cancels, and disputes reservations on behalf of guests.
- A `FrontDeskClerk` performs check-in, check-out, and walk-out at the property.
- A `HousekeepingStaff` cleans rooms, marks rooms in or out of service, and manages maintenance blocks.
- A `Guest` is an end-user who self-serves booking, modification, cancellation, and dispute through the guest portal.

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

Every list endpoint accepts two query parameters: `limit` and `offset`. The default `limit` is 10; values must lie in the inclusive range from 1 to 100. The default `offset` is 0 and must be non-negative. Any value outside these ranges is rejected with `ERR_INVALID_PAGINATION` (HTTP 422). List results are sorted by `created_at` in ascending order, so older records appear first and newer records appear at higher offsets. The `meta` block on every list response surfaces `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true when the number of records following the returned page is greater than zero.

### 2.4. Common Resource Properties and Versioning

Most resources carry the same four common fields. The `id` is a server-minted UUID with no type prefix (no `room_` / `res_` decoration). The `created_at` and `updated_at` timestamps are ISO 8601 UTC strings with three fractional digits. The `version` field is a non-negative integer that begins at 1 on creation and increases by exactly one on every server-side mutation. Two entities are deliberate exceptions: the `ChannelRatePlanMapping` is an immutable join row that carries only `id` and `created_at` — both `updated_at` and `version` are absent — and an `AuditLog` event is an append-only event that likewise carries only `id` and `created_at` and never has an `updated_at` or `version`. For both of these, no PATCH or modification endpoint exists.

### 2.5. Optimistic Concurrency Control

Endpoints that accept structured bodies on a mutating call may include an optional `version` field whose value, if supplied, MUST equal the current `version` of the targeted entity. When supplied and matched, the server performs the mutation and increments `version`. When supplied and mismatched, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Omitting `version` from the body skips the check entirely and the mutation proceeds against the latest state. This control is the second line of defence against lost updates; the first is the per-resource serialization described in §2.7.

### 2.6. Nested Resource Retrieval and Reference Validation

Path parameters are validated **left-to-right**. For an endpoint such as the walkout-cost-estimate read on `(room_type_id, stay_date)`, the server first resolves the `room_type_id` segment; if the `RoomType` does not exist, the response is `ERR_NOT_FOUND` (HTTP 404), and no subsequent segment is evaluated. The same rule applies uniformly to all path parameters that resolve to a `RoomType`, `Room`, `Channel`, `RatePlan`, `RateOverride`, `MaintenanceBlock`, `OverbookingPolicy`, or `Reservation` id. After path parameters resolve, body-level foreign keys (such as the `room_type_id`, `room_id`, `channel_id`, `rate_plan_id` carried in POST/PATCH payloads) are validated against the existence and, where the workflow demands it, the active lifecycle status of the referenced entity; failure here yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404). State preconditions are evaluated only after both forms of existence checks have passed.

### 2.7. Concurrency, Race Resolution, and Serialization Points

The API treats every mutating operation as serializable on a small set of well-defined keys, and the loser of every race receives a specific error. Six races matter:

- **Two confirms on the same reservation.** Serialization is on `Reservation.booking_status`; the first writer wins, and the second writer — finding the reservation already advanced past `PENDING` — is rejected with `ERR_INVALID_STATE` (HTTP 409).
- **Confirms on different reservations competing for the last channel-allotted slot.** Serialization is on the `(room_type_id, stay_date, channel_id)` per-channel inventory decrement. Exactly one confirm succeeds; the loser receives `ERR_INVENTORY_EXHAUSTED` (HTTP 409).
- **Confirms that together push a `(room_type_id, stay_date)` past its overbooking ceiling.** Serialization is on the `(room_type_id, stay_date)` overbooking counter. The loser receives `ERR_OVERBOOKING_LIMIT_EXCEEDED` (HTTP 409).
- **Two check-ins targeting the same physical room.** Serialization is on the `Room.housekeeping_status` transition from `VACANT_CLEAN` to `OCCUPIED`. At most one wins; the loser receives `ERR_ROOM_UNAVAILABLE` (HTTP 409).
- **Approve and reject racing on the same `RateOverride`.** Serialization is on `RateOverride.status`. Exactly one transition wins; the loser receives `ERR_INVALID_STATE` (HTTP 409).
- **Two maintenance blocks with overlapping windows on the same room.** Serialization is on the `(room_id, date)` maintenance occupation. The first writer wins; the second receives `ERR_MAINTENANCE_OVERLAP` (HTTP 409).

### 2.8. Calculation Precision and Rounding

All monetary amounts are stored and returned in **integer cents** (USD). Where a single calculation step requires a non-integer intermediate (a rounded ratio, a commission split, a percentage of the booked total), the result is rounded **half up** to integer cents, and only one rounding step occurs at the end of the calculation — never per night, never per intermediate addend. Capacity-related calculations (channel-allotted shares, overbooking ceilings) are integer counts of rooms; partial allotments use **floor**, never round-up. Basis points are integer counts where 100 bp = 1.00%, so a 1500-bp overbook ratio is +15% and a 250-bp commission is 2.50%.

### 2.9. Validation Priority Ordering

When an endpoint must run several checks before mutating state, the checks are evaluated in a fixed priority order so that the rejection an implementation surfaces is deterministic and matches the testable contract. The ordering is:

1. Authentication header presence (`ERR_AUTH_MISSING`).
2. Role authorisation for the endpoint (`ERR_FORBIDDEN`).
3. Existence of every path-referenced id, resolved left-to-right (`ERR_NOT_FOUND`).
4. Existence and active-lifecycle status of every body-referenced foreign key (`ERR_REFERENCE_NOT_FOUND`).
5. The targeted entity is in a state from which the requested transition is allowed (`ERR_INVALID_STATE`).
6. On a reservation modification, the rate plan permits modifications (`ERR_MODIFICATION_NOT_ALLOWED`).
7. On rate-override approve or reject, segregation of duties is satisfied (`ERR_SEGREGATION_OF_DUTIES`).
8. On reservation check-in, the target room is operationally available and not under any scheduled or active maintenance block (`ERR_ROOM_UNAVAILABLE`).
9. On reservation check-in, the room's room type matches the reservation's room type (`ERR_ROOM_TYPE_MISMATCH`).
10. On reservation create or modify, the rate plan is mapped to the chosen channel and applies to the chosen room type (`ERR_RATE_PLAN_NOT_DISTRIBUTED`).
11. On maintenance-block create, the new block does not overlap any other non-cancelled block on the same room (`ERR_MAINTENANCE_OVERLAP`).
12. On maintenance-block create, the target room is not currently occupied (`ERR_ROOM_CURRENTLY_OCCUPIED`).
13. On channel create or update, `priority_rank` is unique among active channels (`ERR_DUPLICATE_PRIORITY_RANK`).
14. On channel-rate-plan-mapping create, the resulting sum of `inventory_share_basis_points` for the rate plan does not exceed 10000 (`ERR_INVENTORY_SHARE_EXCEEDED`).
15. On reservation confirm, the per-channel inventory share remains at least one for every night (`ERR_INVENTORY_EXHAUSTED`).
16. On reservation confirm and reservation modify, the cumulative reservations across all channels do not exceed the overbooking ceiling for any night (`ERR_OVERBOOKING_LIMIT_EXCEEDED`).
17. On reservation modify, the original `check_in_date` is more than 24 hours in the future at the moment of modification, OR the originating channel's `channel_type` is `DIRECT` (`ERR_MODIFICATION_TOO_LATE`).
18. On reservation cancel, no error is raised on timing — the request is always processed, with the refund tier handling the time-of-cancellation effect.
19. On rate-override create, no other `RateOverride` for the same `(room_type_id, stay_date)` is currently in `DRAFT` or `PENDING_APPROVAL` status (`ERR_OVERRIDE_ALREADY_PENDING`).
20. Pagination parameters fall within their declared bounds (`ERR_INVALID_PAGINATION`).
21. If the request body supplies a `version`, it equals the current entity `version` (`ERR_VERSION_CONFLICT`).

A check earlier in the order surfacing first means a check later in the order is **masked**: a request that would fail both checks 5 and 9 returns the check-5 error. Body-shape problems that aren't covered by any of the above named rules — wrong type, missing required field, an `end_date` not strictly greater than `start_date`, a `base_rate_cents` below 1000, and so on — are rejected with `ERR_INVALID_INPUT` (HTTP 422).

### 2.10. Audit Trail and Append-Only Events

Five categories of decision are written to an append-only audit log: rate-override approval and rejection, an accepted overbooking on a confirm, an executed walk-out, and a detected rate-parity violation across distribution channels. Each event records its `event_type`, the `actor_role` and `actor_id` of whoever (or whatever — `system` is a legal actor) triggered it, the `subject_entity` and `subject_id` of the affected resource, an `occurred_at` server timestamp, and a `payload` object that snapshots the fields relevant to that decision (e.g., `before_rate_cents` and `after_rate_cents` for rate approvals, `compensation_cents` and `reason` for walk-outs). Audit log entries are never updated or deleted; query access is limited to the `PlatformAdmin` and `RevenueManager` roles. The audit-log list endpoint accepts the optional filters `event_type`, `subject_entity`, `subject_id`, `occurred_at_from`, and `occurred_at_to` — the last two narrow the result set to events whose `occurred_at` lies within the supplied half-open instant window.

## 3. Business Logic & Workflows

### 3.1. Inventory Foundation: Room Types, Rooms, and Maintenance

A property is built up from **room types** and the **physical rooms** that realise them. A `PlatformAdmin` defines a room type by submitting its short `code` (uppercase, between 2 and 8 characters, unique among room types not yet retired), a human-readable `name`, a default nightly `base_rate_cents` (which acts as a per-night floor when no override applies and must be at least 1000, i.e. ten dollars), and a `max_occupancy` between 1 and 10 inclusive. Every newly created room type begins life with `status` set to `ACTIVE`; the alternative lifecycle value, `RETIRED`, signals that the type is no longer in inventory but historical reservations against it remain valid. The system maintains a derived `total_physical_rooms` count for each room type — the number of `ACTIVE` `Room` records currently bound to it.

Each physical room is registered against an `ACTIVE` room type by submitting a `room_number` (such as "305" or "12B") that is unique across rooms whose `lifecycle_status` is `ACTIVE`, and the `room_type_id` of the room type it belongs to. A room carries **two parallel state dimensions** that evolve independently: a `housekeeping_status` taking values `VACANT_CLEAN`, `OCCUPIED`, or `DIRTY`; and an `operational_status` taking values `IN_SERVICE` or `OUT_OF_ORDER`. Both default at creation: `housekeeping_status` to `VACANT_CLEAN` and `operational_status` to `IN_SERVICE`. A third dimension, `lifecycle_status`, is either `ACTIVE` (the room counts toward inventory and is selectable for check-in) or `ARCHIVED` (it does not). When a room is occupied, its `current_reservation_id` points to the reservation in residence; for any other housekeeping status, it is null.

The housekeeping cycle moves a room through three positions. Check-in cascades a room from `VACANT_CLEAN` to `OCCUPIED`; check-out cascades it from `OCCUPIED` to `DIRTY`; and a `HousekeepingStaff` member explicitly cleans a `DIRTY` room — provided the room is `IN_SERVICE` — to return it to `VACANT_CLEAN`. The operational dimension is independent of housekeeping. A `HousekeepingStaff` member can take a room out of service, transitioning `operational_status` from `IN_SERVICE` to `OUT_OF_ORDER`, but only when `housekeeping_status` is not `OCCUPIED`. The corresponding return-to-service transition flips `operational_status` from `OUT_OF_ORDER` back to `IN_SERVICE` and is permitted only when no `MaintenanceBlock` for the room is currently in `ACTIVE` status.

A `MaintenanceBlock` schedules a room for repair or refresh over a date window. It carries a `room_id`, a `start_date` (inclusive), an `end_date` (exclusive — the window is the half-open interval beginning at `start_date` and ending strictly before `end_date`, so the day equal to `end_date` is **not** part of the block), a free-text `reason`, and a `status` that defaults to `SCHEDULED`. The `end_date` must be strictly later than the `start_date`. Any attempt to create a block whose half-open interval overlaps any other block on the same room whose `status` is `SCHEDULED` or `ACTIVE` is rejected with `ERR_MAINTENANCE_OVERLAP`. Independently, a block cannot be created on a room whose `housekeeping_status` is currently `OCCUPIED`; that attempt is rejected with `ERR_ROOM_CURRENTLY_OCCUPIED`. Both rules are evaluated at block-creation time.

A `MaintenanceBlock` lifecycle has four positions and three transitions out of `SCHEDULED` or `ACTIVE`. A block transitions from `SCHEDULED` to `ACTIVE` automatically when the logical clock crosses its `start_date` — equivalently, when the current time is at or after `start_date` and strictly before `end_date` — or when an explicit operational change brings the room out of service while the block window covers the present moment. Going active cascades the room: if the room is `IN_SERVICE` and not `OCCUPIED`, its `operational_status` flips to `OUT_OF_ORDER`. A block transitions from `ACTIVE` to `RELEASED` either automatically when the clock crosses `end_date` or by an explicit release call from `HousekeepingStaff` or `PlatformAdmin`. The release cascade restores the room only if no other `ACTIVE` block still covers it — in that case `operational_status` returns to `IN_SERVICE`, and `housekeeping_status` is set to `DIRTY` on the assumption the technician left the room dusty. A `SCHEDULED` block may also be cancelled by a `HousekeepingStaff` member, advancing `status` to `CANCELLED`; the precondition is that the block is still `SCHEDULED` (an `ACTIVE` block cannot be cancelled — it must be released).

### 3.2. Distribution: Channels, Rate Plans, and Channel-Rate-Plan Mappings

A distribution `Channel` represents a downstream surface that can sell room nights. A `PlatformAdmin` registers a channel by supplying its uppercase short `code` (unique across active channels), its `channel_type` (one of `DIRECT`, `OTA`, `GDS`, `WHOLESALER`), a `commission_basis_points` value between 0 and 5000 inclusive (so commissions range from zero up to 50%), and a `priority_rank` of at least 1. The lower the `priority_rank`, the higher the channel's priority for inventory release; ranks are unique across active channels, and any attempted duplicate is rejected with `ERR_DUPLICATE_PRIORITY_RANK`. The lifecycle `status` of a channel is `ACTIVE` by default; the alternative value is `SUSPENDED`.

A `RatePlan` defines what guests booking through one or more channels actually pay against a particular room type. A `PlatformAdmin` or `RevenueManager` creates a rate plan with its uppercase short `code` (unique across active plans), the `room_type_id` it applies to, a `refund_tier_code` taking one of the four values `FLEXIBLE`, `MODERATE`, `STRICT`, or `NON_REFUNDABLE`, and a boolean `modification_allowed` flag (which defaults to true). The lifecycle `status` of a rate plan is `ACTIVE` by default with `RETIRED` as the only other value.

The bridge between a channel and a rate plan is a `ChannelRatePlanMapping`. A `PlatformAdmin` or `RevenueManager` creates the mapping by supplying the `channel_id`, the `rate_plan_id`, and an `inventory_share_basis_points` in the inclusive range from 0 to 10000 — the share, in basis points, of the room-type's inventory allocated to this channel for this rate plan on any given date. Because mappings are immutable join rows, the only fields they expose are `id` and `created_at`; there is no `updated_at` or `version`. The mapping carries an `enabled` flag (defaulting to true) that the system may flip to suppress channel-side inventory release without deleting the row. On creation, the system validates that the sum of `inventory_share_basis_points` across all mappings sharing the same `rate_plan_id` does not exceed 10000 after the new row is taken into account; if it would, the request is rejected with `ERR_INVENTORY_SHARE_EXCEEDED`. The 10000-basis-point ceiling is the one-hundred-percent allocation cap.

### 3.3. The Pricing Engine: Rate Overrides, Approval Chain, and Parity Monitoring

Default nightly pricing is whatever each room type's `base_rate_cents` says it is. A `RevenueAnalyst` may propose a deviation for a specific date by creating a `RateOverride`, supplying the `room_type_id`, the `stay_date` (a single ISO date), the `proposed_rate_cents` (which must be at least 1000), and the `recommendation_source` — either `SYSTEM_ENGINE` (a forecasting tool generated the proposal) or `MANUAL_OVERRIDE` (a human authored it). The override is born in `DRAFT` status, with `applied_rate_cents` null, `approved_by` null, and `status` exactly equal to `DRAFT`. At most one `RateOverride` per `(room_type_id, stay_date)` may be in either `DRAFT` or `PENDING_APPROVAL` status at any time; an attempt to create a second one in either of those states is rejected with `ERR_OVERRIDE_ALREADY_PENDING`. Note that `APPROVED`, `REJECTED`, and `SUPERSEDED` overrides do not block a fresh proposal — the constraint is only on overrides still in flight.

The submitting analyst advances a `DRAFT` to `PENDING_APPROVAL` by submitting it; the room type must still be `ACTIVE` and the `stay_date` must not be in the past at submission time. From `PENDING_APPROVAL`, three transitions are possible. A `RevenueManager` may approve, advancing `status` to `APPROVED`; or reject, advancing `status` to `REJECTED`; or the original `RevenueAnalyst` may withdraw, returning the override to `DRAFT` for revision (this cyclic loop supports iterative revision rounds). On both approve and reject, the segregation-of-duties rule applies: the `X-User-ID` of the approver MUST NOT equal the `X-User-ID` recorded as the submitter. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Approval is the consequential transition. It sets `applied_rate_cents` equal to `proposed_rate_cents`, captures the approving `RevenueManager`'s `X-User-ID` into `approved_by`, and triggers two cascades. First, any prior `RateOverride` for the same `(room_type_id, stay_date)` whose `status` is `APPROVED` is moved to `SUPERSEDED` — only one approved override per slot is ever effective. Second, the system runs the **rate-parity check** across every enabled `ChannelRatePlanMapping` whose rate plan belongs to the same room type. Approval also writes a `RATE_OVERRIDE_APPROVED` audit event whose payload contains the before-rate and after-rate cents; rejection writes a `RATE_OVERRIDE_REJECTED` audit event.

The rate-parity check projects the now-effective nightly rate onto each enabled mapping and compares the resulting commission-grossed rates across the OTA and GDS channels. For each enabled mapping whose `rate_plan` belongs to the affected room type, the channel-observed rate is the effective rate multiplied by the quantity of ten thousand plus the channel's `commission_basis_points`, divided by ten thousand — that is, the effective rate scaled up by the channel's commission to recover what the guest will see post-commission. Only mappings whose channel has `channel_type` of `OTA` or `GDS` participate in the parity comparison; `DIRECT` and `WHOLESALER` channels are excluded. The parity tolerance is one hundred basis points: if, across the participating channels, the largest channel-observed rate divided by the smallest exceeds the smallest by more than one percent, an audit event of type `RATE_PARITY_VIOLATION_DETECTED` is written, with a payload identifying the room type, the stay date, the maximum observed rate, and the minimum observed rate. Detection is informational — it does not block the approval — but it is the operational signal a `RevenueManager` watches.

### 3.4. Overbooking Policy and Walkout Cost Estimation

A `RevenueManager` configures overbooking on a per-`(room_type, stay_date)` basis by creating an `OverbookingPolicy`. The policy carries the `room_type_id`, the `stay_date`, an `overbook_ratio_basis_points` value in the inclusive range from 0 to 5000 (so up to +50% over physical capacity), an `estimated_no_show_probability_basis_points` value in the inclusive range from 0 to 10000 (a forecast of what fraction of confirmed bookings will not show), and a `walkout_compensation_cents` value of at least zero — the per-walked-out-guest compensation cost the property has committed to. A policy is born in `ACTIVE` status; creating a fresh policy for the same `(room_type_id, stay_date)` cascades any prior `ACTIVE` policy on that key to `SUPERSEDED`, so only one policy is ever effective per slot.

Revenue planning consumes overbooking via a read-only walkout-cost estimate exposed for any `(room_type_id, stay_date)` that has an `ACTIVE` policy. The response carries an object with the `room_type_id`, the `stay_date`, the projected `expected_walkouts`, and the projected `estimated_cost_cents`. The projection is **forward-looking** and is computed at read time from current state. The reservation count for the date is the number of reservations whose `booking_status` is `CONFIRMED`, whose `room_type_id` matches, and whose stay window covers the date (i.e., `stay_date` falls in the half-open interval beginning at the reservation's `check_in_date` and ending strictly before its `check_out_date`). The physical capacity is the count of rooms of the matching room type whose `lifecycle_status` is `ACTIVE`, minus the count of maintenance blocks on those rooms whose `status` is `SCHEDULED` or `ACTIVE` and whose half-open window covers the date. The expected number of arrivals is the reservation count multiplied by the quantity of ten thousand minus the policy's `estimated_no_show_probability_basis_points`, divided by ten thousand. The expected walkouts is whichever is greater of zero and the difference between expected arrivals and physical capacity. The estimated cost in cents is the expected walkouts multiplied by the policy's `walkout_compensation_cents`, with the final result rounded half-up to integer cents.

The realised cost on an actual walk-out, by contrast, is computed from the walked-out reservation alone. When a `FrontDeskClerk` executes a walk-out, the `walkout_compensation_cents` recorded on the `Reservation` is the policy's `walkout_compensation_cents` for the reservation's `(room_type_id, check_in_date)` multiplied by the reservation's `nights`. There is no probability factor and no projection: it is a direct per-night-per-guest amount realised at the moment of execution. As a consequence, the estimated cost a planner reads in the morning and the realised cost a single walk-out books in the afternoon are different numbers by construction, even when only one walk-out occurs that day — the estimate spreads cost across an expected fraction of arriving guests, the realised charge applies the full per-night compensation to the actual reservation.

### 3.5. The Reservation Lifecycle: Booking, Confirmation, Modification, Cancellation

A reservation begins life when a `ReservationsAgent` or `Guest` creates it, supplying the `guest_name`, the `room_type_id`, the `rate_plan_id`, the `channel_id`, the `check_in_date` (inclusive — the first night of stay), and the `check_out_date` (exclusive — the morning of departure, where `nights` is the whole-day difference between `check_out_date` and `check_in_date` and `check_out_date` MUST be strictly later than `check_in_date`). The reservation list endpoint also accepts two optional date filters, `check_in_date_from` and `check_in_date_to`, which together narrow the result to reservations whose `check_in_date` falls within the supplied inclusive lower bound and exclusive upper bound respectively. On creation, the reservation is born in `booking_status` of `PENDING` and `payment_status` of `UNPAID`. The `payment_status` field takes values from the set `UNPAID`, `AUTHORIZED`, `CAPTURED`, `REFUNDED_PARTIAL`, `REFUNDED_FULL`, and `CHARGEBACK` — the last value is reserved for adverse downstream-payment-system outcomes that an external integration may post; the API itself does not transition into `CHARGEBACK`. Several derived fields begin at known initial values: `assigned_room_id` is null (no specific room is reserved yet, only a room type), `nights` is the whole-day difference described above, `booked_total_cents` is zero (the rate is not locked until confirmation), `refund_amount_cents` is zero, `no_show_charge_cents` is zero, `walkout_compensation_cents` is zero, `cancelled_at` is null, and `dispute_status` is `NONE`. The reservation also implicitly records the `channel_id` and `rate_plan_id` chosen at creation. At creation time and again at modification time, the system enforces that the `RatePlan`'s `room_type_id` equals the reservation's `room_type_id` AND that a `ChannelRatePlanMapping` exists between the chosen `channel_id` and `rate_plan_id` whose `enabled` flag is true; failure of either is rejected with `ERR_RATE_PLAN_NOT_DISTRIBUTED`.

Confirmation moves the reservation from `PENDING` to `CONFIRMED`. Only a `ReservationsAgent` may confirm. The transition runs three pre-checks in order, and only after all three pass is the rate locked and the booking advanced. First, the rate plan and channel must still be active and the channel-rate-plan mapping must still be `enabled`; the rate plan's `status` must be `ACTIVE` and its `room_type_id` must match the reservation's `room_type_id`, the channel's `status` must be `ACTIVE`, and the mapping's `enabled` must be true. Second, the **per-channel inventory share must remain at least one for every night in the stay window**. For each date in the half-open interval beginning at `check_in_date` and ending strictly before `check_out_date`, the physical capacity for the date is the number of rooms of the reservation's room type whose `lifecycle_status` is `ACTIVE`, minus the count of maintenance blocks on those rooms whose `status` is `SCHEDULED` or `ACTIVE` and whose half-open window covers that date. The channel's allotted share is that physical capacity multiplied by the `inventory_share_basis_points` of the relevant `ChannelRatePlanMapping`, divided by ten thousand, and then **floored** to an integer count of rooms (partial allotments do not round up). The number already used by this channel on that date is the count of reservations whose `channel_id` and `rate_plan_id` equal the candidate's, whose `booking_status` is `CONFIRMED` or `CHECKED_IN`, and whose stay window covers the date. The remaining is the channel share minus the used count; if the minimum remaining across all nights is not greater than zero, the confirm is rejected with `ERR_INVENTORY_EXHAUSTED`. Third, the **cumulative reservations across all channels must not exceed the overbooking ceiling on any night**. For each night, the policy's `overbook_ratio_basis_points` (or zero if no `ACTIVE` policy exists for that `(room_type_id, stay_date)`) is multiplied by the physical capacity and floored to give the overbooking allowance; the ceiling is physical capacity plus that allowance. The candidate is added to the cumulative count of `CONFIRMED` and `CHECKED_IN` reservations covering that night, and if the resulting count is **strictly greater than** the ceiling, the confirm is rejected with `ERR_OVERBOOKING_LIMIT_EXCEEDED`. The boundary is strict: a count equal to the ceiling is full but legal; only counts strictly exceeding the ceiling are forbidden.

When all three checks pass, the system computes the `booked_total_cents` by walking each date in the stay window: for each date, if a `RateOverride` for this room type and this `stay_date` exists with `status` of `APPROVED`, the per-night rate is its `applied_rate_cents`; otherwise, it is the room type's `base_rate_cents`. The booked total is the sum of those per-night cents amounts; because each per-night value is already integer cents, the sum is exact and no rounding step is needed. The lock at confirmation also sets `payment_status` to `AUTHORIZED`. If the confirm landed inside the overbooking allowance — i.e., the cumulative count exceeded physical capacity but stayed at or below the ceiling — the system writes an `OVERBOOKING_ACCEPTED` audit event.

Modification of a `CONFIRMED` reservation is initiated by a `ReservationsAgent` or `Guest` who submits new `check_in_date` and `check_out_date` values, optionally with a `version` field for optimistic concurrency. Modification is rejected with `ERR_INVALID_STATE` if the reservation is not in `CONFIRMED`, with `ERR_MODIFICATION_NOT_ALLOWED` if the rate plan's `modification_allowed` is false, and with `ERR_MODIFICATION_TOO_LATE` if the original `check_in_date` is **at or within 24 hours** of the moment of modification AND the originating channel's `channel_type` is **not** `DIRECT` (direct bookings retain modification rights inside the 24-hour window). When permitted, modification re-runs both the per-channel inventory and the overbooking ceiling check against the new dates, recomputes `booked_total_cents` against the **current** applicable rates (so a rate override approved between original confirmation and modification will surface in the new total), increments `version`, and refreshes `updated_at`. The transition is cyclic from `CONFIRMED` back to `CONFIRMED` and may iterate.

Cancellation may be initiated from either `PENDING` or `CONFIRMED` by a `ReservationsAgent` or `Guest`; cancellation timing never produces an error of its own — the time of cancellation only affects the refund tier. On cancellation, the system records `cancelled_at` as the server clock at the moment of the request. From `PENDING`, the reservation has never been charged: `refund_amount_cents` is set to zero, and if `payment_status` was `AUTHORIZED` it is moved to `REFUNDED_FULL` (otherwise unchanged). From `CONFIRMED`, the system computes a tiered refund. The lead-time-hours figure is the local-midnight-of-`check_in_date` minus `cancelled_at`, expressed in hours. The applicable refund ratio in basis points is then read from the rate plan's `refund_tier_code`:

- For `FLEXIBLE`, the refund ratio is 10000 bp (a full refund) when `lead_time_hours` is at least 24, and 5000 bp (a half refund) otherwise.
- For `MODERATE`, the refund ratio is 10000 bp when `lead_time_hours` is at least 168 (one week), 5000 bp when `lead_time_hours` is at least 72 but less than 168, and 0 bp (no refund) when `lead_time_hours` is less than 72.
- For `STRICT`, the refund ratio is 5000 bp when `lead_time_hours` is at least 336 (two weeks), and 0 bp otherwise.
- For `NON_REFUNDABLE`, the refund ratio is 0 bp at any lead time.

The refund amount in cents is the `booked_total_cents` multiplied by the chosen ratio in basis points, divided by ten thousand, with a single half-up rounding applied to the final result — never a per-night refund and never an intermediate rounding. If the resulting `refund_amount_cents` is greater than zero, the `payment_status` becomes `REFUNDED_PARTIAL` when the refund is strictly less than `booked_total_cents` and `REFUNDED_FULL` otherwise. If the refund is zero, the `payment_status` becomes `CAPTURED` — the property has retained the full booking value as a cancellation penalty.

### 3.6. The Front Desk: Check-In, Check-Out, and Walk-Out

Check-in is performed by a `FrontDeskClerk` who supplies the specific physical `room_id` to assign. The reservation must be in `CONFIRMED`; the calendar today must be at or after `check_in_date`. The chosen room must satisfy four conditions: the room's `room_type_id` matches the reservation's `room_type_id` (a mismatch surfaces as `ERR_ROOM_TYPE_MISMATCH`); the room's `lifecycle_status` is `ACTIVE`; the room's `operational_status` is `IN_SERVICE` and there is no `MaintenanceBlock` with `status` of either `SCHEDULED` or `ACTIVE` overlapping any night in the reservation's half-open stay window (failure on either part of this surfaces as `ERR_ROOM_UNAVAILABLE`); and the room's `housekeeping_status` is `VACANT_CLEAN` (failure here also surfaces as `ERR_ROOM_UNAVAILABLE`). When all four hold, the system sets the reservation's `assigned_room_id` to the supplied `room_id`, cascades the room from `VACANT_CLEAN` to `OCCUPIED`, sets the room's `current_reservation_id` to the reservation's id, and advances `payment_status` to `CAPTURED`.

Check-out, also performed by a `FrontDeskClerk`, advances the booking from `CHECKED_IN` to `CHECKED_OUT` and cascades the room from `OCCUPIED` to `DIRTY`, while also clearing the room's `current_reservation_id` back to null. Check-out is the trigger for the **channel-commission settlement** calculation: the commission amount in cents is the reservation's `booked_total_cents` multiplied by the originating channel's `commission_basis_points`, divided by ten thousand, with a single half-up rounding step, and the net to the hotel is the `booked_total_cents` minus the commission amount. Both figures use one rounding step against integer cents.

A walk-out is the front-desk recovery path when a `CONFIRMED` reservation arrives but no physical room of the booked room type is actually available. A `FrontDeskClerk` may execute the walk-out only when today equals the reservation's `check_in_date` (walk-out only happens at intended arrival, not days later) and the count of physical rooms of the matching room type that are simultaneously `VACANT_CLEAN`, `IN_SERVICE`, and free of any overlapping `MaintenanceBlock` is zero. The transition advances `booking_status` to `WALKED_OUT`, sets `walkout_compensation_cents` to the realised amount described in §3.4, advances `payment_status` to `REFUNDED_FULL`, and writes a `WALKOUT_EXECUTED` audit event whose payload contains `compensation_cents` and a `reason`.

### 3.7. Time-Triggered Outcomes: No-Show, Block Activation, and the Logical Clock

The system runs on a server-controlled logical clock. A `PlatformAdmin` may advance that clock by submitting a `new_now` ISO 8601 instant; the response reports the new `now` and the `transitions_triggered` array — a list of `{entity, id, from, to}` records that captures every state change the advance caused. Three classes of transition are time-driven and surface in this list. First, a `Reservation` whose `booking_status` is `CONFIRMED` and whose `assigned_room_id` is null transitions automatically to `NO_SHOW` once `now()` is at or after the reservation's `check_in_date` plus 24 hours. Second, a `MaintenanceBlock` in `SCHEDULED` activates as soon as `now()` is at or after `start_date` and strictly before `end_date`. Third, a `MaintenanceBlock` in `ACTIVE` releases as soon as `now()` is at or after `end_date`. The current logical instant is also readable on demand and is exposed to every authenticated role as an object containing a single `now` field. A complementary `from` / `to` pair on each transition record makes the before-and-after states explicit for any consumer.

When a reservation transitions to `NO_SHOW`, the system computes `no_show_charge_cents` from the rate plan's `refund_tier_code`. For `NON_REFUNDABLE` and `STRICT` tiers, the charge is the full `booked_total_cents`. For `MODERATE`, the charge is the booked total multiplied by 5000, divided by ten thousand, with one half-up rounding step (a 50% charge). For `FLEXIBLE`, the charge is the booked total multiplied by 1000, divided by ten thousand, with one half-up rounding step (a 10% charge). The `dispute_status` initialises to `NONE`. If the resulting `no_show_charge_cents` is greater than zero, `payment_status` advances to `CAPTURED`. The corresponding `refund_amount_cents` for a no-show stays at zero — the no-show charge is the financial outcome on this path.

### 3.8. Disputes

A `Guest` or `ReservationsAgent` may open a dispute against a reservation that has gone to `NO_SHOW` or `CANCELLED` with a residual penalty. Opening a dispute moves `dispute_status` from `NONE` to `OPEN`. Resolving a dispute is a `PlatformAdmin` operation that takes a `resolution` body field whose value is one of two strings: `GUEST` or `HOTEL`. When `resolution` is `GUEST`, the system reverses the financial outcome — the `refund_amount_cents` is set to whichever penalty applied (the `no_show_charge_cents` if the reservation reached `NO_SHOW`, or the `booked_total_cents` minus any prior refund where applicable for a `CANCELLED` case) — `payment_status` is moved to `REFUNDED_FULL`, and `dispute_status` advances to `RESOLVED_GUEST`. When `resolution` is `HOTEL`, no monetary change occurs and `dispute_status` advances to `RESOLVED_HOTEL`. Disputes are terminal once resolved.

### 3.9. Sibling Symmetry Across the Reservation Terminal States

For symmetry of specification across the four ways a reservation can reach a terminal state, the rules above can be summarised in parallel form. A `CHECKED_OUT` reservation is the success path: payment is `CAPTURED` at check-in and the channel commission settlement is computed at check-out. A `CANCELLED` reservation has `cancelled_at` set, a tiered `refund_amount_cents` computed (from a `CONFIRMED` origin) or zero (from a `PENDING` origin), and a `payment_status` of `REFUNDED_FULL`, `REFUNDED_PARTIAL`, or `CAPTURED` according to the refund magnitude. A `NO_SHOW` reservation has `no_show_charge_cents` computed by tier, `payment_status` of `CAPTURED` if the charge is positive, and `dispute_status` initialised to `NONE`. A `WALKED_OUT` reservation has `walkout_compensation_cents` computed at execution from the reservation's `nights` and the active policy's per-guest compensation, and `payment_status` set to `REFUNDED_FULL`. Each path leaves a deterministic financial settlement on the reservation row.

## 4. Endpoint Definitions

The endpoint table below summarises every operation the API supports. Operations that **create** a fresh resource return HTTP 201 on success; every other 2xx response is HTTP 200. Request bodies, response bodies, and side effects are described in the §3 narratives — this table only lists method, path, description, and the roles authorized to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /hotel/room-types | Create a room type | PlatformAdmin |
| GET | /hotel/room-types | List room types (filter by status) | PlatformAdmin, RevenueAnalyst, RevenueManager, ReservationsAgent, FrontDeskClerk, HousekeepingStaff |
| GET | /hotel/room-types/{id} | Read a room type | PlatformAdmin, RevenueAnalyst, RevenueManager, ReservationsAgent, FrontDeskClerk, HousekeepingStaff |
| POST | /hotel/rooms | Create a physical room and bind to a room type | PlatformAdmin |
| GET | /hotel/rooms | List rooms (filter by room_type_id, housekeeping_status, operational_status, lifecycle_status) | PlatformAdmin, FrontDeskClerk, HousekeepingStaff, RevenueAnalyst, RevenueManager |
| POST | /hotel/rooms/{id}/clean | Mark a DIRTY room as VACANT_CLEAN | HousekeepingStaff |
| POST | /hotel/rooms/{id}/out-of-service | Mark a Room operational_status as OUT_OF_ORDER | HousekeepingStaff |
| POST | /hotel/rooms/{id}/return-to-service | Mark a Room operational_status as IN_SERVICE | HousekeepingStaff |
| POST | /hotel/maintenance-blocks | Schedule a maintenance block on a room (half-open [start, end)) | HousekeepingStaff, PlatformAdmin |
| POST | /hotel/maintenance-blocks/{id}/release | Manually release an ACTIVE maintenance block | HousekeepingStaff, PlatformAdmin |
| POST | /hotel/maintenance-blocks/{id}/cancel | Cancel a SCHEDULED maintenance block | HousekeepingStaff, PlatformAdmin |
| POST | /hotel/channels | Create a distribution channel | PlatformAdmin |
| GET | /hotel/channels | List channels | PlatformAdmin, RevenueAnalyst, RevenueManager, ReservationsAgent |
| POST | /hotel/rate-plans | Create a rate plan scoped to one room type | PlatformAdmin, RevenueManager |
| POST | /hotel/channel-rate-plan-mappings | Map a rate plan to a channel with an inventory share | PlatformAdmin, RevenueManager |
| POST | /hotel/rate-overrides | Create a rate override (DRAFT) | RevenueAnalyst, RevenueManager |
| POST | /hotel/rate-overrides/{id}/submit | Submit DRAFT rate override for approval | RevenueAnalyst |
| POST | /hotel/rate-overrides/{id}/approve | Approve a PENDING_APPROVAL rate override | RevenueManager |
| POST | /hotel/rate-overrides/{id}/reject | Reject a PENDING_APPROVAL rate override | RevenueManager |
| POST | /hotel/rate-overrides/{id}/withdraw | Withdraw a PENDING_APPROVAL rate override back to DRAFT | RevenueAnalyst |
| POST | /hotel/overbooking-policies | Create an overbooking policy for (room_type, date) | RevenueManager |
| GET | /hotel/overbooking-policies/{room_type_id}/{stay_date}/walkout-cost-estimate | Read forward-looking estimated walkout cost for a (room_type, date) | RevenueAnalyst, RevenueManager |
| POST | /hotel/reservations | Create a Reservation in PENDING | ReservationsAgent, Guest |
| GET | /hotel/reservations | List reservations (filter by booking_status, channel_id, room_type_id, check_in_date_from, check_in_date_to) | ReservationsAgent, FrontDeskClerk, RevenueAnalyst, RevenueManager, PlatformAdmin |
| GET | /hotel/reservations/{id} | Read a reservation | ReservationsAgent, FrontDeskClerk, RevenueAnalyst, RevenueManager, PlatformAdmin, Guest |
| POST | /hotel/reservations/{id}/confirm | Confirm a PENDING reservation; locks rate | ReservationsAgent |
| POST | /hotel/reservations/{id}/modify | Modify a CONFIRMED reservation's dates | ReservationsAgent, Guest |
| POST | /hotel/reservations/{id}/cancel | Cancel a PENDING or CONFIRMED reservation; computes refund | ReservationsAgent, Guest |
| POST | /hotel/reservations/{id}/check-in | Check the guest into a specific Room | FrontDeskClerk |
| POST | /hotel/reservations/{id}/check-out | Check the guest out | FrontDeskClerk |
| POST | /hotel/reservations/{id}/walk-out | Execute walk-out workflow at intended arrival when no room available | FrontDeskClerk |
| POST | /hotel/reservations/{id}/dispute | Open a dispute against a NO_SHOW or CANCELLED reservation's penalty | Guest, ReservationsAgent |
| POST | /hotel/reservations/{id}/resolve-dispute | Resolve an OPEN dispute in favor of guest (refund) or hotel (no refund) | PlatformAdmin |
| GET | /hotel/audit-logs | List audit log events (filter by event_type, subject_entity, subject_id, occurred_at_from/to) | PlatformAdmin, RevenueManager |
| POST | /_clock/advance | Advance the server's logical clock to drive time-gated transitions | PlatformAdmin |
| GET | /_clock | Read current logical clock | PlatformAdmin, RevenueAnalyst, RevenueManager, ReservationsAgent, FrontDeskClerk, HousekeepingStaff, Guest |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_MODIFICATION_NOT_ALLOWED | 409 |
| ERR_MODIFICATION_TOO_LATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_ROOM_UNAVAILABLE | 409 |
| ERR_ROOM_TYPE_MISMATCH | 422 |
| ERR_RATE_PLAN_NOT_DISTRIBUTED | 422 |
| ERR_MAINTENANCE_OVERLAP | 409 |
| ERR_ROOM_CURRENTLY_OCCUPIED | 409 |
| ERR_DUPLICATE_PRIORITY_RANK | 409 |
| ERR_INVENTORY_SHARE_EXCEEDED | 422 |
| ERR_INVENTORY_EXHAUSTED | 409 |
| ERR_OVERBOOKING_LIMIT_EXCEEDED | 409 |
| ERR_OVERRIDE_ALREADY_PENDING | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_INVALID_PAGINATION | 422 |
| ERR_INVALID_INPUT | 422 |
