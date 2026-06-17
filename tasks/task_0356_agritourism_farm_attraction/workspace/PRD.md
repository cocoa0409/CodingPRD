# Agritourism Farm Attraction API — Product Requirements Document

## 1. Introduction

A seasonal farm attraction — think a pumpkin patch wrapped around a corn maze — sells far more than a single ticket. On any October weekend the same operator is metering how many guests can be on the property during a given hour, selling hayride and maze passes, weighing pumpkins on a scale at the exit, quoting discounted rates to a visiting third-grade class, honoring season passes, and watching the sky for the storm that will force everything to shut down at once. This API is the system of record behind that operation. It governs timed admission and capacity, activity passes, weight- and quantity-based pumpkin pricing, group and school rates, season passes, weather-driven closures, parking and concessions, and the liability waivers every participant must sign before stepping onto a hayride.

The product's central tension is that capacity is scarce and contested while pricing is multi-layered and frequently revised. A timed admission window holds only so many participants; reservations and group bookings compete for those seats, and the system must keep its seat accounting exact even as holds convert to commitments, cancellations free inventory back up, and a weather closure voids an entire afternoon in a single cascade. At the same time, the same admission can be priced provisionally at booking and re-settled at the gate, a pumpkin can be charged on an estimate and then re-charged on the scale, and a group's quote can be revised any number of times before it is locked in with a deposit. Getting both the capacity ledger and the money exactly right — under concurrent writers and sudden weather — is the whole job.

Four kinds of users share the system. A `FarmManager` configures the farm, its pricing, and its windows, and declares weather. A `Visitor` registers, buys passes, and books and pays for their own visits. A `GroupLeader` organizes a field-trip, school, or corporate group through a quote-and-revise cycle. A `GateAgent` works the property on the day — checking guests in, weighing pumpkins, settling tabs, and sweeping no-shows.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `FarmManager`, `Visitor`, `GroupLeader`, and `GateAgent`. When a request is authenticated but the acting role is not permitted to perform the requested operation, the response is `ERR_FORBIDDEN_ROLE`.

Two of the roles are tied to a persisted entity, and two are operational identities. When `X-User-Role` is `Visitor`, `X-User-ID` is the `id` of the acting `Visitor`; ownership checks on any resource that references a `Visitor` compare the resource's foreign-key field to `X-User-ID`. In particular, a `Visitor` owns the `Reservation` records they created (the comparison is against the reservation's `visitor_id`). When `X-User-Role` is `GroupLeader`, `X-User-ID` is likewise the `id` of an acting `Visitor` — a group leader is a visitor acting in an organizer capacity — and ownership of a `GroupBooking` is established by comparing the booking's `group_leader_id` to `X-User-ID`. When an entity-backed user targets a resource they do not own, the operation is rejected with `ERR_NOT_OWNER`; this guard covers the reservation-owner actions (confirm, cancel, and the attachment of activity passes, waivers, and pumpkin purchases) and the group-booking leader actions (revise, requote, edit, confirm, and cancel).

When `X-User-Role` is `FarmManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `GateAgent`, `X-User-ID` is similarly an opaque operator identifier not tied to any persisted entity — the gate agent who weighs a pumpkin or checks a reservation in is authorized by role alone, and the server does not match the agent's id against any owner field.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. The one documented exception is the weather-event log for a farm, which is presented newest-first.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 (or the server's initial value) and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.8.

One entity is deliberately exempt from this convention. A `WeatherEvent` is an append-only log record: it is created once and never mutated. A `WeatherEvent` therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field. Every other entity in the system (`Farm`, `PricingPolicy`, `AdmissionWindow`, `Visitor`, `SeasonPass`, `Reservation`, `ActivityPass`, `Waiver`, `PumpkinPurchase`, `ConcessionOrder`, and `GroupBooking`) carries the full `id` / `created_at` / `updated_at` / `version` quartet.

Whenever the server recomputes a derived value on a resource — a window's seat counts, a farm's posture, a reservation's settled charge — that recomputation is a mutation: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Hierarchical Consistency and Cascades

Resources form a hierarchy, and a state change at the top can ripple all the way down. The deepest such ripple is the weather-closure cascade, which runs three levels deep and resolves atomically inside the single request that triggers it (the system's consistency model is immediate — there are no deferred or eventual reconciliations). When a farm closes, the affected admission windows are cancelled, the live reservations on those windows are cancelled, and the downstream credits and pass adjustments are applied — all before the response is returned. The detailed semantics of that cascade live in §3.6.

Two derived fields are kept continuously reconciled against their children. A window's seat counts (`seats_held`, `seats_committed`, `seats_available`) are recomputed from the reservations and group bookings that draw on the window every time one of those children is created, confirmed, cancelled, checked in, marked no-show, or swept by a closure. A reservation's two join flags (`checkout_finalized`, `waiver_satisfied`) are recomputed from its pumpkin purchases and waivers as those children change. Because each such reconciliation mutates the parent, it refreshes the parent's `updated_at` and bumps its `version` per §2.4.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many paths address a resource nested under one or more parents. The server validates the existence of path and body references left-to-right: each path identifier is checked in order, and only then are foreign-key references in the request body validated. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` immediately, before any later identifier or any business rule is evaluated. For example, a request to list the reservations on a window whose id does not exist fails with `ERR_NOT_FOUND` for the window, never reaching the reservation lookup. This existence check sits at validation priority 3, after authentication and authorization but ahead of every state and business rule below.

The hierarchy is also reverse-reachable: every child collection can be listed under its parent. Activity passes, waivers, pumpkin purchases, and concession orders each hang off a reservation (each carries the `reservation_id` of its owning reservation), and listing them is scoped to that reservation. Likewise reservations are reachable through their `window_id`, `visitor_id`, `season_pass_id`, or `group_booking_id`, and split sub-groups are reachable through their `parent_group_id`.

### 2.7. Monetary Values, Weights, and Precision

All money in the system is expressed in integer cents. Admission prices, pass prices, line totals, deposits, wallet credits, and grand totals are all whole numbers of cents; there are no fractional cents anywhere in stored state or in responses. Where a calculation multiplies cents by a fractional factor — a group discount, a per-pound pumpkin rate — the result is rounded to a whole number of cents using the round-half-up convention, and the rounding is applied exactly once at the point each calculation specifies (never per-line-item when the rule says round the sum). Deposits are the one exception to round-half-up: a group deposit is rounded up to the next whole cent (ceiling), as detailed in §3.8.

Weights are pounds and may be fractional: a pumpkin's `estimated_weight_lb` and `scale_weight_lb`, and a policy's `heavy_pumpkin_lb` breakpoint, are decimal numbers. Only the resulting charge is rounded to cents.

Independent of the domain rules below, every request body is first checked for structural well-formedness: a malformed body, a missing required field, an unrecognized enum value, or a numeric value that falls outside its stated range (for example a negative cents amount, a non-positive weight, or a discount percentage that is not at least 0 and strictly below 1) is rejected with `ERR_VALIDATION`. This basic input check is applied wherever a field's documented type, enumeration, or numeric constraint is violated.

### 2.8. Optimistic Concurrency Control on Window Capacity

Because admission windows are the scarce, contested resource, two write paths that commit seats against a window are guarded by optimistic concurrency control keyed on the window's `version`. In both cases the request must carry `expected_window_version`, the value of the target `AdmissionWindow`'s `version` that the client last observed, and in both cases a mismatch against the window's current `version` is rejected with `ERR_WINDOW_VERSION_STALE` (HTTP 412).

The first guarded path is reservation creation. A request to create a reservation must carry `expected_window_version` matching the target window's current `version`; if another writer has advanced the window's `version` since the client last read it — for instance by placing a competing hold that legitimately consumed inventory — the create is rejected with `ERR_WINDOW_VERSION_STALE`, preventing the client from booking against a seat count it never actually saw. The second guarded path is group-booking confirmation, which commits a whole block of seats at once: that request also carries `expected_window_version`, and if the window's `version` has advanced since the leader last requoted, the confirm is rejected with `ERR_WINDOW_VERSION_STALE`. Both rejections carry HTTP status 412. No other endpoint takes a window version field; mutations outside these two paths perform no OCC check.

### 2.9. Farm Posture as an Operational Gate

A farm is always in one of three operational postures, exposed as `operational_status`: `OPEN`, `WEATHER_HOLD`, or `CLOSED`. This posture is never set directly by a client — it is derived from the most recent weather event applied to the farm, and the farm also keeps `active_weather_event_id` as a back-pointer to the event currently driving its posture (null when none). The posture gates which child operations are permitted, and the precise gating rules are woven into the workflows of §3: in broad strokes, a farm that is not `OPEN` refuses new admission, while a farm under a hold still permits gate operations that a closed farm does not.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Farm: Posture, Pricing, and Windows

A `FarmManager` creates a farm by supplying its `name` and, optionally, its `timezone` (the IANA zone used to interpret window local times, defaulting to `America/Chicago`), its `parking_fee_cents` (the flat per-vehicle parking charge, defaulting to 1000 cents — ten dollars — and never negative), and its `window_buffer_minutes` (the minimum cleanup gap required between two windows on the farm, defaulting to 30 minutes and never negative). A new farm opens for business immediately: its `operational_status` starts at `OPEN`, its `active_weather_event_id` is null, and its `refunds_issued_cents` — the running total of admission cents auto-refunded by weather closures — starts at 0.

Before a farm can price anything it needs a `PricingPolicy`. A manager drafts a policy against a farm by supplying the full rate card: the per-adult and per-child timed-admission prices (`adult_admission_cents`, `child_admission_cents`), the three activity-pass prices (`hayride_pass_cents`, `maze_pass_cents`, `upick_pass_cents`), the pumpkin rates (`pumpkin_per_lb_cents` and `pumpkin_flat_each_cents`), and the season-pass price (`season_pass_price_cents`) — each of these is a count of cents and may not be negative. The policy also carries the parameters that drive discounts and pumpkin pricing: `heavy_pumpkin_lb`, the weight breakpoint in pounds at which a pumpkin flips from per-pound to flat-each pricing (defaulting to 20 and required to be greater than 0); `group_rate_min_headcount`, the minimum number of participants for a group to qualify for a discount (defaulting to 15 and at least 1); `group_discount_pct`, the fractional discount applied to qualifying groups (defaulting to 0.20, meaning twenty percent off, and constrained to be at least 0 and strictly below 1); and `school_discount_pct`, the deeper fractional discount applied instead of the group discount when the group is a school (defaulting to 0.35 and likewise at least 0 and strictly below 1). The policy's `farm_id` ties it to its farm.

A freshly created policy has `status` of `DRAFT`. A manager activates a policy to put it into force; activation sets that policy's `status` to `ACTIVE` and, if some other policy on the same farm was already `ACTIVE`, demotes that prior policy's `status` to `SUPERSEDED` — only one policy per farm is `ACTIVE` at any moment. Activating a policy that is already `ACTIVE` or already `SUPERSEDED` is rejected with `ERR_POLICY_ALREADY_ACTIVE`. Pricing operations that need a live rate card — issuing a season pass, attaching an activity pass, computing an admission or pumpkin charge — depend on the farm having exactly one `ACTIVE` policy; when none exists, the operation is rejected with `ERR_NO_ACTIVE_POLICY`.

Timed capacity is sold through admission windows. A manager creates an `AdmissionWindow` on a farm by giving its `starts_at`, its `ends_at`, and its `capacity` — the maximum total participants, held plus committed, the window will admit (at least 1). The window's `farm_id` ties it to its farm. A new window begins with `status` of `SCHEDULED`, with `seats_held` and `seats_committed` both at 0 and `seats_available` equal to its `capacity`. A window's start must fall strictly before its end; a window whose `starts_at` is not strictly before its `ends_at` (including a zero-length window) is rejected with `ERR_WINDOW_TIME_INVALID`. A new window must also not collide with any existing non-cancelled window on the same farm once the farm's cleanup buffer is taken into account. Treating each window's occupied span as the half-open interval from its `starts_at` (inclusive) to its `ends_at` (exclusive), two windows collide unless one ends far enough ahead of the other that the gap is at least the buffer: specifically, they do not collide only when the first window's `ends_at` plus the buffer is at or before the second's `starts_at`, or the second's `ends_at` plus the buffer is at or before the first's `starts_at`. A gap of exactly `window_buffer_minutes` is allowed; any gap shorter than the buffer — including overlap and back-to-back scheduling — is a collision rejected with `ERR_WINDOW_OVERLAP`. Cancelled windows are ignored when checking for collisions.

A window's `status` is otherwise system-driven. It flips to `SOLD_OUT` the moment a reservation create or confirm drives its `seats_available` to exactly 0, and it flips back to `SCHEDULED` when a later cancellation frees a seat so that `seats_available` is again greater than 0. The only other terminal possibility, `CANCELLED`, is reached solely through the weather-closure cascade described in §3.6; a window is never cancelled directly and, once cancelled, is never revived even if the farm reopens.

### 3.2. Visitors, Season Passes, and Wallet Credit

Anyone transacting must first exist as a `Visitor`. A visitor is registered with an `email` (their unique contact address) and a `full_name`; registration may be performed by a visitor themselves or by a `FarmManager` on their behalf. A new visitor's `wallet_credit_cents` — the refund and credit balance that weather closures and overpayment accrue, redeemable against a future tab — starts at 0.

A `SeasonPass` admits its holder to a farm across a validity span. A pass is issued against a farm for a given visitor, carrying the pass's `farm_id`, the holder's `visitor_id`, the first admitting instant `valid_from` (inclusive), and the last admitting instant `valid_until` (exclusive). At issue the pass's `purchase_price_cents` is snapshotted from the farm's `ACTIVE` policy's `season_pass_price_cents`, its `status` is set to `ACTIVE`, and its `visits_used` count — how many reservations have redeemed it — starts at 0. A pass may be issued by the holder or by a manager. A visitor may not hold two overlapping `ACTIVE` passes on the same farm: treating each pass's validity as the half-open interval from `valid_from` (inclusive) to `valid_until` (exclusive), a new pass collides with an existing `ACTIVE` pass for the same visitor and farm unless one's `valid_until` is at or before the other's `valid_from`. Back-to-back passes where one's `valid_until` exactly equals the next's `valid_from` leave no gap yet do not collide, because the intervals are half-open. A genuine overlap is rejected with `ERR_PASS_OVERLAP`.

A manager may revoke a pass, moving its `status` to `REVOKED`. Revoking a pass that is already `REVOKED` is rejected with `ERR_PASS_ALREADY_REVOKED`. A pass may also be in `EXPIRED` status once its validity has elapsed. A pass's `visits_used` rises and falls with the reservations that redeem it, as described in the reservation lifecycle below.

### 3.3. Booking a Reservation: Holds, Confirmation, and the Capacity Ledger

A `Visitor` books a timed visit by creating a `Reservation`. The create payload names the `window_id` of the desired window, the `visitor_id` of the owner, the `adult_count` and `child_count` of the party (each at least 0), and the `expected_window_version` token for the optimistic-concurrency check of §2.8; it may optionally name a `season_pass_id` to redeem a pass instead of paying per head, and a `group_booking_id` to attach the reservation to a confirmed group. The system derives `participant_count` as the sum of `adult_count` and `child_count`; this is the number of seats the reservation draws against the window and must be at least 1 — an empty party is rejected with `ERR_EMPTY_PARTY`.

A reservation create is admitted only when the world is in order, and the checks are evaluated in a fixed order so that the most fundamental failure is the one reported. Authentication comes first, then role authorization, then the existence of every referenced resource (window, visitor, and any named pass or group), then — for an entity-backed owner — ownership. The farm must be `OPEN`: a create attempted while the owning farm is on a weather hold or closed is rejected with `ERR_FARM_NOT_OPEN`. The target window must not be `CANCELLED`; a create against a closure-cancelled window is rejected with `ERR_WINDOW_CANCELLED`, and this holds even after the farm reopens, because a cancelled window admits nothing. If a `season_pass_id` is supplied, the referenced pass must belong to the same visitor and the same farm, must be `ACTIVE`, and its validity span must cover the window's `starts_at`; any failure here is `ERR_PASS_NOT_VALID`. If a `group_booking_id` is supplied, that group must sit on the very same window as the reservation, or the create is rejected with `ERR_GROUP_WINDOW_MISMATCH`. The party must be non-empty (`ERR_EMPTY_PARTY`). The window must have at least `participant_count` seats available before the hold is placed, or the create is rejected with `ERR_WINDOW_SOLD_OUT`. Finally the optimistic-concurrency token is checked: `expected_window_version` must equal the window's current `version`, failing which the create is rejected with `ERR_WINDOW_VERSION_STALE`.

A successful create lands the reservation in `PENDING` status, places a hold by adding `participant_count` to the window's `seats_held`, recomputes `seats_available`, flips the window to `SOLD_OUT` if availability has reached 0, computes the provisional `admission_charge_cents` (the provisional pricing variant of §3.5), and increments the window's `version` by one. The reservation's `settled_charge_cents` remains unset until check-in.

Confirming a reservation converts the hold into a firm commitment. Confirmation is permitted only on a `PENDING` reservation whose owning farm is `OPEN` and whose window is not `CANCELLED`, and — if the reservation redeems a pass — only when that pass is `ACTIVE` and its validity covers the window start (the same `ERR_PASS_NOT_VALID` guard applies). Confirmation moves the reservation `PENDING → CONFIRMED`, subtracts `participant_count` from the window's `seats_held` and adds it to `seats_committed`, recomputes `seats_available`, flips the window to `SOLD_OUT` if availability reaches 0, re-pins the provisional `admission_charge_cents`, and — when a pass is redeemed — increments that pass's `visits_used` by one. A confirm against a farm that is not `OPEN` is rejected with `ERR_FARM_NOT_OPEN`; against a cancelled window, `ERR_WINDOW_CANCELLED`; and a transition attempted from a status other than `PENDING` is rejected with `ERR_INVALID_STATE`.

A `Visitor` may cancel their own reservation while it is `PENDING` or `CONFIRMED`. Cancellation releases the inventory the reservation was holding: if the reservation was `PENDING`, `participant_count` is subtracted from `seats_held`; if it was `CONFIRMED`, `participant_count` is subtracted from `seats_committed`; in either case `seats_available` is recomputed and a `SOLD_OUT` window flips back to `SCHEDULED` once availability exceeds 0. Cancellation revokes every child `ActivityPass` (their `status` becomes `REVOKED`), voids every child `Waiver` (`VOID`), voids every child `PumpkinPurchase` (`VOID`), and refunds every child `ConcessionOrder` (`REFUNDED`). A self-initiated cancellation does not credit the visitor's wallet — only a weather closure credits, per §3.6. Cancelling a reservation that is neither `PENDING` nor `CONFIRMED` is rejected with `ERR_INVALID_STATE`.

The window's seat counts are always reconcilable from first principles, and the system keeps them so. The held count is the sum of `participant_count` over the window's `PENDING` reservations. The committed count is the sum of `participant_count` over the window's reservations in `CONFIRMED`, `CHECKED_IN`, or `SETTLED` status, plus the sum of `headcount` over the `CONFIRMED` group bookings on that window. Available seats are the window's `capacity` less held less committed, floored at 0 so the figure is never negative. Reservations in `NO_SHOW` or `CANCELLED` status, and groups in `QUOTED`, `REVISING`, or `CANCELLED` status, contribute to neither sum.

### 3.4. At the Gate: Check-In, Weigh-Out, and Settlement

The day-of flow is run by a `GateAgent` and forks a checked-in reservation into two independent finalization legs that must both complete before the reservation can settle.

Before a reservation can be checked in, every participant must be covered by a signed waiver. A `Visitor` signs a `Waiver` against their reservation by giving the `participant_name`; the payload also carries `is_minor` (defaulting to false) and, for a minor, the `guardian_name`. A waiver for a minor that omits `guardian_name` is rejected at signing with `ERR_GUARDIAN_REQUIRED`. A new waiver's `status` is `SIGNED`. As waivers are added, the reservation's `waiver_satisfied` flag is recomputed; it becomes true once a `SIGNED` waiver covers every participant.

Checking a reservation in is permitted only on a `CONFIRMED` reservation, only while the owning farm is `OPEN` or under a `WEATHER_HOLD` (a hold does not block check-in, but a `CLOSED` farm does), only when the window is not `CANCELLED`, and only when `waiver_satisfied` is true — a check-in attempted before a signed waiver covers every participant is rejected with `ERR_WAIVER_INCOMPLETE`. A transition attempted from a status other than `CONFIRMED` is rejected with `ERR_INVALID_STATE`. Check-in moves the reservation `CONFIRMED → CHECKED_IN`, recomputes and locks the `settled_charge_cents` (the settled pricing variant of §3.5), recomputes `waiver_satisfied`, and opens the fork: the pumpkin weigh-out leg and the checkout-finalize leg now proceed independently.

On the pumpkin leg, a `Visitor` adds a `PumpkinPurchase` to their reservation's checkout by declaring its `estimated_weight_lb` (a positive number). The add computes a provisional `charge_cents` from that estimate (the estimate variant of §3.5), sets the purchase's `status` to `ESTIMATED`, and marks the reservation's `checkout_finalized` flag false (an unweighed pumpkin keeps checkout open). At the scale, a `GateAgent` records the authoritative `scale_weight_lb` via a weigh-out; this writes `scale_weight_lb`, recomputes `charge_cents` from the scale weight (the scale variant of §3.5), moves the purchase `ESTIMATED → WEIGHED`, and recomputes the reservation's `checkout_finalized`, which becomes true once no `ESTIMATED` pumpkin remains. Weighing out a pumpkin that is already `WEIGHED` or `VOID` is rejected with `ERR_PUMPKIN_ALREADY_WEIGHED`.

The two legs join at settlement. A `GateAgent` settles a `CHECKED_IN` reservation, which is permitted only when both legs are complete: `checkout_finalized` is true (every pumpkin is `WEIGHED`, or there are none) and `waiver_satisfied` is true. A settle attempted while a pumpkin is still `ESTIMATED` or while the waiver is not satisfied — that is, before the join condition is met — is rejected with `ERR_CHECKOUT_NOT_FINALIZED`. Settlement moves the reservation `CHECKED_IN → SETTLED` and locks it: no further child mutations are permitted. A settle from a status other than `CHECKED_IN` is rejected with `ERR_INVALID_STATE`.

A reservation that was confirmed but never checked in can be swept to a no-show. After a window's `ends_at` has passed (relative to the server's current clock), a `GateAgent` sweeps the window: each reservation still in `CONFIRMED` status whose window has ended is moved `CONFIRMED → NO_SHOW`, releasing its `participant_count` from the window's `seats_committed` and recomputing `seats_available`. A no-show still consumes the visit — if the reservation redeemed a pass, that pass's `visits_used` is left unchanged by the sweep.

### 3.5. Pricing: Admission, Pumpkins, and the Grand Total

Admission is priced twice over a reservation's life, and the two computations can diverge. The base admission is the `adult_count` multiplied by the policy's `adult_admission_cents` plus the `child_count` multiplied by the policy's `child_admission_cents`. If the reservation belongs to a group booking that is `CONFIRMED`, a discount applies to that base: the rate is the policy's `school_discount_pct` when the group's `kind` is `SCHOOL`, and the policy's `group_discount_pct` otherwise; the discounted base is the base multiplied by one minus that rate, rounded half-up to whole cents exactly once after the multiply. If the reservation redeems a pass that is `ACTIVE`, admission is waived entirely and the charge is 0; otherwise the charge is the (possibly discounted) base. The **provisional** variant is computed at create and re-pinned at confirm into `admission_charge_cents`, and it reads the group's status as of that moment — a reservation created before its group is `CONFIRMED` carries no discount. The **settled** variant is recomputed at check-in into `settled_charge_cents`, re-evaluating the group's status as of check-in; a reservation whose group became `CONFIRMED` between create and check-in is discounted at settle though it was not at create, so the two figures legitimately differ for the same party.

A pumpkin is likewise priced twice. The charge turns on whether the pumpkin's weight reaches the policy's `heavy_pumpkin_lb` breakpoint: a pumpkin whose weight is at or above the breakpoint is a heavy pumpkin and is charged the flat `pumpkin_flat_each_cents` regardless of exact weight; a pumpkin below the breakpoint is charged per pound, its weight multiplied by `pumpkin_per_lb_cents` and rounded half-up to whole cents. The comparison is inclusive at the breakpoint — a pumpkin weighing exactly `heavy_pumpkin_lb` is flat-each, not per-pound. The **estimate** variant runs at add using the visitor-declared `estimated_weight_lb` and stores into `charge_cents` while the purchase is `ESTIMATED`; the **scale** variant runs at weigh-out using the authoritative `scale_weight_lb`, overwrites `charge_cents`, and sets the purchase `WEIGHED`. If the scale weight crosses the breakpoint that the estimate missed, the same physical pumpkin flips from per-pound to flat-each and the two charges diverge.

A concession order rolls up parking and food. When a `Visitor` or `GateAgent` adds a `ConcessionOrder` to a reservation, the payload carries `food_cents` (the food and beverage subtotal, defaulting to 0, never negative) and `vehicle_count` (the number of vehicles parked, defaulting to 0, never negative). At create the order's `parking_cents` is computed as `vehicle_count` multiplied by the farm's `parking_fee_cents` (snapshotted at create), its `total_cents` is `food_cents` plus `parking_cents`, and its `status` is `PAID`.

Each activity pass carries its own line total. When a `Visitor` attaches an `ActivityPass` to a reservation, the payload names the `activity` (`HAYRIDE`, `MAZE`, or `UPICK`) and the `quantity` (at least 1). At attach, the pass's `unit_price_cents` is snapshotted from the `ACTIVE` policy's matching activity rate — `hayride_pass_cents`, `maze_pass_cents`, or `upick_pass_cents` — its `line_total_cents` is `quantity` multiplied by `unit_price_cents`, and its `status` is `ACTIVE`.

The reservation's running tab is available as a computed read that returns the reservation with its `gross_cents` and `net_due_cents` populated. The total is assembled in a pinned order so the figure is well-defined. First, admission: the `settled_charge_cents` if the reservation is `CHECKED_IN` or `SETTLED`, otherwise the provisional `admission_charge_cents`. Second, activities: the sum of `line_total_cents` across the reservation's `ACTIVE` activity passes. Third, pumpkins: the sum of `charge_cents` across the reservation's purchases in `ESTIMATED` or `WEIGHED` status. Fourth, concessions: the sum of `total_cents` across the reservation's `PAID` concession orders. The `gross_cents` is the sum of those four. Wallet credit is applied strictly last: the applied credit is the smaller of the visitor's `wallet_credit_cents` and `gross_cents` (so it can never exceed the gross), and `net_due_cents` is `gross_cents` minus that applied credit. All inputs are already whole cents, so no rounding is needed in this assembly. This read does not persist anything.

### 3.6. Weather: Holds, Clearances, and the Closure Cascade

Weather is the system's most consequential event, and only a `FarmManager` declares it, by recording a `WeatherEvent` against a farm. The event carries its `farm_id`, its `kind` (`HOLD`, `CLEARED`, or `CLOSURE`), an optional free-text `note`, and — for a closure — the `affected_span_start` (inclusive) and `affected_span_end` (exclusive) bounding the span of windows the closure cancels. After the event is applied, the system snapshots the farm's resulting posture onto the event's `resulting_status`.

A `HOLD` declared on an `OPEN` farm moves its `operational_status` `OPEN → WEATHER_HOLD` and sets `active_weather_event_id` to the new event. Under a hold, new reservation creation is blocked (a create attempt returns `ERR_FARM_NOT_OPEN`), but check-in, weigh-out, and refund cleanup continue. A `CLEARED` event declared while the farm is on a hold moves it `WEATHER_HOLD → OPEN`, clears `active_weather_event_id` to null, and resumes reservation creation. A `CLEARED` event declared while the farm is `CLOSED` reopens posture `CLOSED → OPEN` and clears `active_weather_event_id`, but does not revive any window the closure cancelled — only posture reopens.

A `CLOSURE` is the cascade root, permitted whenever the farm is not already `CLOSED`, and it runs three levels deep within the single request. At the first level, every admission window on the farm whose `starts_at` falls inside the closure's affected span and whose `status` is not already `CANCELLED` is moved to `CANCELLED`. The farm's `operational_status` moves to `CLOSED` and `active_weather_event_id` is set to the new event. At the second level, each window cancellation drives its own children: every reservation on that window in `PENDING` or `CONFIRMED` status is moved to `CANCELLED` with closure as the cause, and the window's `seats_held` and `seats_committed` are reset to 0 with `seats_available` recomputed. At the third level, each closure-caused reservation cancellation, unlike a self-cancellation, does credit the visitor: if the reservation redeemed a pass, that pass's `visits_used` is decremented by one; the visitor's `wallet_credit_cents` is increased by the reservation's `admission_charge_cents`; and the farm's `refunds_issued_cents` is increased by that same `admission_charge_cents`. As with any reservation cancellation, each cascaded reservation also revokes its activity passes (`REVOKED`), voids its waivers (`VOID`), voids its pumpkin purchases (`VOID`), and refunds its concession orders (`REFUNDED`). The whole three-level cascade — window cancellations, reservation cancellations, wallet credits, pass decrements, and refund rollups — completes atomically before the closure response returns.

### 3.7. Group Bookings: Quote, Revise, Confirm

A `GroupLeader` organizes a larger party through a `GroupBooking`, which runs a cyclic quote-and-revise loop before locking in. The leader creates a booking against a farm by naming the `window_id` the group will occupy, the `group_leader_id` who owns it, the `kind` (`FIELD_TRIP`, `SCHOOL`, or `CORPORATE`), and the `adult_count` (chaperones) and `child_count` (students), each at least 0; the booking also carries its `farm_id`. A booking may optionally name a `parent_group_id` when it is a split chaperone sub-group of a larger booking — this is a self-reference to another `GroupBooking`, and is null for a top-level group. On creation the booking's `headcount` is the sum of `adult_count` and `child_count`, its `quoted_total_cents` is computed by the group-quote rule below, and its `status` is `QUOTED`.

The group-quote computation takes the booking's `adult_count`, `child_count`, and `kind` together with the `ACTIVE` policy's rates and discount parameters. The per-head base is `adult_count` multiplied by `adult_admission_cents` plus `child_count` multiplied by `child_admission_cents`. The group qualifies for a discount only when its `headcount` is at least the policy's `group_rate_min_headcount`; if it qualifies, the rate is `school_discount_pct` when the `kind` is `SCHOOL` and `group_discount_pct` otherwise, and if it does not qualify the rate is zero. The `quoted_total_cents` is the per-head base multiplied by one minus that rate, rounded half-up to whole cents exactly once after the multiply — the sum is rounded, not each head individually.

The leader may open a `QUOTED` booking for editing, moving it `QUOTED → REVISING`; from `REVISING` the leader may edit the headcount and kind, then requote to move it `REVISING → QUOTED`, which recomputes `quoted_total_cents` from the updated figures. A leader may cycle through revise and requote any number of rounds before confirming. The edit operation on a revising booking accepts a new `adult_count`, `child_count`, and/or `kind` and updates those fields but does not itself requote — the quote refreshes only on requote. Opening for revision, requoting, or editing a booking that is not in the required `QUOTED` or `REVISING` state is rejected with `ERR_GROUP_NOT_REVISABLE`.

Confirmation locks the group in and commits its block of seats. A leader may confirm a `QUOTED` booking only when the owning farm is `OPEN`, the window is not `CANCELLED`, the `headcount` is at least 1, the window has at least `headcount` seats available, and the supplied `expected_window_version` matches the window's current `version`. These map to specific rejections: a farm that is not `OPEN` yields `ERR_FARM_NOT_OPEN`; a cancelled window yields `ERR_WINDOW_CANCELLED`; an empty group yields `ERR_EMPTY_PARTY`; insufficient seats yield `ERR_WINDOW_SOLD_OUT`; a stale version yields `ERR_WINDOW_VERSION_STALE`; and a confirm attempted from a status other than `QUOTED` yields `ERR_INVALID_STATE`. A successful confirm moves the booking `QUOTED → CONFIRMED`, locks the `deposit_cents` at the ceiling of `quoted_total_cents` multiplied by one quarter (the non-refundable deposit is rounded up so it is never under a quarter of the quote), adds `headcount` to the window's `seats_committed`, recomputes `seats_available`, flips the window to `SOLD_OUT` if availability reaches 0, and increments the window's `version` by one.

A leader may cancel a booking only while it is `QUOTED` or `REVISING`, moving it to `CANCELLED`; a `CONFIRMED` group cannot be cancelled, because its deposit is non-refundable and its seats are committed. A cancel attempted on a booking that is neither `QUOTED` nor `REVISING` is rejected with `ERR_INVALID_STATE`.

### 3.8. Test-Driving the Clock

Several behaviors are time-gated: a no-show sweep depends on a window's `ends_at` lying in the past, and a pass's validity depends on the current instant relative to its `valid_from` and `valid_until`. To make these deterministic, an administrative test-driving capability lets a `FarmManager` set the server's current UTC clock to a supplied `to_iso8601` instant. This advances or resets the logical clock that the sweep and validity checks read against; it persists nothing else.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or list, or that drive a state transition or other modification on an existing resource, return `200 OK`. All listing endpoints honor the pagination and sort conventions of §2.3, and accept the `status` (and, where noted, `kind` or `visitor_id`) filter query parameters in addition to `limit` and `offset`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/farms` | Create a farm (posture starts OPEN) | FarmManager |
| GET | `/farms/{id}` | Read a farm | FarmManager, Visitor, GroupLeader, GateAgent |
| POST | `/farms/{id}/weather-events` | Record a weather event (drives posture and closure cascade) | FarmManager |
| GET | `/farms/{id}/weather-events` | List weather events for a farm (newest first) | FarmManager, Visitor, GroupLeader, GateAgent |
| POST | `/farms/{id}/pricing-policies` | Create a pricing policy (DRAFT) | FarmManager |
| POST | `/pricing-policies/{id}/activate` | Activate a pricing policy (supersedes prior active) | FarmManager |
| GET | `/pricing-policies/{id}` | Read a pricing policy | FarmManager, Visitor, GroupLeader, GateAgent |
| GET | `/farms/{id}/pricing-policies` | List pricing policies for a farm | FarmManager, Visitor, GroupLeader, GateAgent |
| POST | `/farms/{id}/admission-windows` | Create a timed admission window | FarmManager |
| GET | `/admission-windows/{id}` | Read a window | FarmManager, Visitor, GroupLeader, GateAgent |
| GET | `/farms/{id}/admission-windows` | List windows for a farm | FarmManager, Visitor, GroupLeader, GateAgent |
| POST | `/admission-windows/{id}/mark-no-shows` | Sweep ended CONFIRMED reservations to NO_SHOW | GateAgent |
| GET | `/admission-windows/{id}/reservations` | List reservations on a window | FarmManager, Visitor, GroupLeader, GateAgent |
| GET | `/admission-windows/{id}/group-bookings` | List group bookings on a window | FarmManager, Visitor, GroupLeader, GateAgent |
| POST | `/visitors` | Register a visitor | FarmManager, Visitor |
| GET | `/visitors/{id}` | Read a visitor | FarmManager, Visitor |
| GET | `/visitors/{id}/season-passes` | List a visitor's season passes | FarmManager, Visitor |
| GET | `/visitors/{id}/group-bookings` | List group bookings led by a visitor | FarmManager, GroupLeader, Visitor |
| POST | `/farms/{id}/season-passes` | Issue a season pass to a visitor | FarmManager, Visitor |
| GET | `/season-passes/{id}` | Read a season pass | FarmManager, Visitor |
| GET | `/farms/{id}/season-passes` | List season passes for a farm | FarmManager, Visitor |
| POST | `/season-passes/{id}/revoke` | Revoke a season pass | FarmManager |
| POST | `/reservations` | Create a reservation (places hold; OCC on window version) | Visitor |
| GET | `/reservations/{id}` | Read a reservation | FarmManager, Visitor, GroupLeader, GateAgent |
| GET | `/visitors/{id}/reservations` | List a visitor's reservations | FarmManager, Visitor |
| GET | `/season-passes/{id}/reservations` | List reservations that redeemed a pass | FarmManager, Visitor |
| GET | `/group-bookings/{id}/reservations` | List reservations under a group | FarmManager, GroupLeader |
| GET | `/reservations/{id}/total` | Computed read: reservation grand total | FarmManager, Visitor, GateAgent |
| POST | `/reservations/{id}/confirm` | Confirm a PENDING reservation | Visitor |
| POST | `/reservations/{id}/cancel` | Cancel a PENDING/CONFIRMED reservation | Visitor |
| POST | `/reservations/{id}/check-in` | Check in a CONFIRMED reservation | GateAgent |
| POST | `/reservations/{id}/settle` | Settle a CHECKED_IN reservation | GateAgent |
| POST | `/reservations/{id}/activity-passes` | Attach an activity pass | Visitor |
| GET | `/reservations/{id}/activity-passes` | List activity passes on a reservation | FarmManager, Visitor, GateAgent |
| POST | `/reservations/{id}/waivers` | Sign a participant waiver | Visitor |
| GET | `/reservations/{id}/waivers` | List waivers on a reservation | FarmManager, Visitor, GateAgent |
| POST | `/reservations/{id}/pumpkin-purchases` | Add a pumpkin with an estimated weight | Visitor |
| POST | `/pumpkin-purchases/{id}/weigh-out` | Record authoritative scale weight | GateAgent |
| GET | `/reservations/{id}/pumpkin-purchases` | List pumpkin purchases on a reservation | FarmManager, Visitor, GateAgent |
| POST | `/reservations/{id}/concession-orders` | Add a concession/parking order | Visitor, GateAgent |
| GET | `/reservations/{id}/concession-orders` | List concession orders on a reservation | FarmManager, Visitor, GateAgent |
| POST | `/farms/{id}/group-bookings` | Create a group booking quote | GroupLeader |
| GET | `/group-bookings/{id}` | Read a group booking | FarmManager, GroupLeader, Visitor |
| GET | `/farms/{id}/group-bookings` | List group bookings for a farm | FarmManager, GroupLeader |
| GET | `/group-bookings/{id}/sub-groups` | List split sub-groups | FarmManager, GroupLeader |
| PATCH | `/group-bookings/{id}` | Edit headcount/kind on a REVISING group | GroupLeader |
| POST | `/group-bookings/{id}/revise` | Open a QUOTED group for editing | GroupLeader |
| POST | `/group-bookings/{id}/requote` | Recompute the quote and return to QUOTED | GroupLeader |
| POST | `/group-bookings/{id}/confirm` | Confirm a QUOTED group (commit seats; OCC on window version) | GroupLeader |
| POST | `/group-bookings/{id}/cancel` | Cancel a QUOTED/REVISING group booking | GroupLeader |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | FarmManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FARM_NOT_OPEN` | 409 |
| `ERR_WINDOW_TIME_INVALID` | 422 |
| `ERR_EMPTY_PARTY` | 422 |
| `ERR_WINDOW_SOLD_OUT` | 409 |
| `ERR_WINDOW_VERSION_STALE` | 412 |
| `ERR_WAIVER_INCOMPLETE` | 422 |
| `ERR_GUARDIAN_REQUIRED` | 422 |
| `ERR_PASS_NOT_VALID` | 422 |
| `ERR_GROUP_WINDOW_MISMATCH` | 422 |
| `ERR_PASS_ALREADY_REVOKED` | 409 |
| `ERR_PUMPKIN_ALREADY_WEIGHED` | 409 |
| `ERR_CHECKOUT_NOT_FINALIZED` | 409 |
| `ERR_GROUP_NOT_REVISABLE` | 409 |
| `ERR_NO_ACTIVE_POLICY` | 409 |
| `ERR_POLICY_ALREADY_ACTIVE` | 409 |
| `ERR_WINDOW_CANCELLED` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_PASS_OVERLAP` | 409 |
