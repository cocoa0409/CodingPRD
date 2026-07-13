# Ice Rink & Learn-to-Skate API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Ice Rink & Learn-to-Skate API, the operational backbone of a community ice arena. A single facility juggles a surprising number of overlapping concerns on the same sheet of ice: public-skate sessions with rental-skate inventory, tiered learn-to-skate curricula with prerequisite gating, hockey and figure leagues with seasonal lockers, private rentals and broomball, birthday parties, walk-up blade sharpening, and recurring monthly tuition. Every one of these activities competes for the same finite resource — ice time — and each carries its own money movement against a prepaid skater wallet.

The central discipline the API enforces is temporal: ice slots must respect opening hours and leave a resurfacing (Zamboni) buffer between bookings, lockers cannot be double-assigned for overlapping date ranges, and time-gated actions such as completing a slot or rolling a billing cycle forward depend on a server-controlled logical clock rather than wall-clock time. Layered on top are quota rules (public-skate capacity, class capacity, league rosters, locker and rental-skate inventory), dual-variant pricing (peak versus off-peak rentals, calendar versus session-based tuition proration), and cascading cancellations that must unwind child bookings and refund wallets consistently. The requirements below define these behaviors precisely so that a compliant implementation is unambiguous.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly three roles, spelled precisely as `RinkManager`, `FrontDesk`, and `Skater`. If either header is missing, or if `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. Even the bootstrap operations that create the first rinks and skaters require a valid operator role in the header — there is no anonymous access. When a caller is authenticated but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The `RinkManager` is the operational superset role. A `RinkManager` schedules and manages ice slots (create, publish, unpublish, cancel, complete), creates rinks, learn-to-skate classes, and leagues, performs administrative wallet adjustments, advances tuition billing cycles, completes enrollments, starts and cancels leagues, completes slot bookings, and sets the logical clock. Beyond those exclusive powers, a `RinkManager` may also perform any of the shared customer-facing actions on behalf of any skater. When `X-User-Role` is `RinkManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

The `FrontDesk` role covers desk operations: it exclusively advances sharpening orders through their steps and refunds public-skate admissions, and it shares the ability to register skaters, admit skaters to public-skate sessions, submit sharpening orders, and read resources. When `X-User-Role` is `FrontDesk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

The `Skater` role represents a registered customer acting on their own resources: admitting themselves, enrolling themselves, creating and paying and cancelling their own tuition subscription, registering themselves for leagues, assigning and releasing their own lockers, booking their own slots, submitting and reading their own sharpening orders. When `X-User-Role` is `Skater`, `X-User-ID` is the `id` of the acting `Skater`; ownership checks on any resource that references a skater compare the resource's `skater_id` to `X-User-ID`. A `Skater` who attempts to act on a resource whose `skater_id` is not their own is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and must lie between a minimum of 1 and a maximum of 100 inclusive. A `limit` outside that range is a malformed request and is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Gated Operations

All time-dependent rules in this system are evaluated against a server-controlled **logical clock**, never the machine's wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, every time comparison uses that default — the server never falls back to real time. A `RinkManager` may reposition the clock (forward or backward) by supplying a `to_iso8601` instant; the operation returns the new clock value as `current_utc`. Advancing or rewinding the clock changes the outcome of every time-gated rule described below, including ice-slot completion (which requires the clock to have reached a slot's `end_utc`), slot-booking completion (which requires the clock to have reached the booked slot's `end_utc`), tuition cycle advancement (which requires the clock to have reached `billing_cycle_end`), and the cancellation date used for tuition proration.

### 2.5. Common Resource Properties and Versioning

Every resource in this system is system-addressable and carries a standard set of managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation.
- `version` — an integer that starts at creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control (see §2.6).

All entity types in this API carry the full set of the four fields above. Whenever the server changes a resource — whether from a direct client request or as an automatic reconciliation triggered elsewhere — it refreshes that resource's `updated_at` and increments its `version`.

### 2.6. Optimistic Concurrency Control for Tuition Subscriptions

Creating a recurring tuition subscription is guarded by optimistic concurrency control on its parent enrollment. Because a newly created `ACTIVE` subscription legitimately supersedes any prior `ACTIVE` subscription on the same enrollment — the prior one is cancelled as a side effect — a client working from a stale view of the enrollment must be prevented from silently creating a second, superseding subscription. Accordingly, the create-subscription request carries a mandatory `expected_enrollment_version` field holding the client's last observed `version` of the target `Enrollment`. If that value does not equal the enrollment's current `version` at the time of the request — meaning another writer has advanced the enrollment since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint in the system takes a version field; only subscription creation performs this check.

### 2.7. The Skater Wallet, Money Movement, and Precision

A skater is registered by a `RinkManager` or `FrontDesk` operator with a `full_name`, a unique `email` (no two skaters may share an email), and an optional `membership` of either `MEMBER` or `NON_MEMBER` (defaulting to `NON_MEMBER`); membership status governs the rental-quote discount described in §3.6. Each skater holds a prepaid wallet balance, `wallet_credit_cents`, denominated in integer cents and defaulting to 0. Charges deduct from it and refunds credit back to it. Whenever an operation would charge more than the wallet holds — an admission fee, a locker fee, a tuition monthly fee, or a slot-booking quote — the request is rejected with `ERR_INSUFFICIENT_FUNDS` and no money moves. A `RinkManager` may directly adjust a wallet (for comps or top-ups) by posting an `amount_cents` delta, which is added to `wallet_credit_cents` and may be negative to debit; an optional `reason` may accompany the adjustment. Such an adjustment increments the skater's `version`.

All monetary and count fields are integers of cents or whole units. Wherever a rule divides or multiplies to produce a cents amount — tuition proration and party tax being the two cases — the result is rounded to a whole number of cents using the round-half-up method (a value ending in exactly half a cent rounds up). Capacity, inventory, and queue figures are exact integer counts.

### 2.8. Hierarchical Consistency and Cascading State

Many operations mutate more than one resource. When a parent resource is cancelled or completed, the system propagates the consequence to its children immediately and in the same transaction, refunding wallets and restoring inventory as required, and each affected resource independently has its `updated_at` refreshed and its `version` incremented. Conversely, some parent states are *derived* from children: a learn-to-skate class flips between `OPEN` and `FULL` purely as a function of how many enrollments it holds, without any direct request against the class itself. The specific cascade chains — ice-slot cancellation unwinding admissions, classes, and bookings; class cancellation withdrawing enrollments; enrollment withdrawal cancelling tuition; league cancellation releasing lockers — are described in §3 where each workflow lives.

### 2.9. Nested Resource Retrieval and Validation Ordering

Requests are validated in a fixed priority order, and the first failing check determines the error returned:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform this operation per §2.1, and for a `Skater` acting on its own resource the `X-User-ID` matches the resource's `skater_id`, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource referenced by a path identifier or a foreign-key body field (rink, ice slot, skater, class, enrollment, subscription, league, registration, locker assignment, slot booking, sharpening order) must exist. Path identifiers are checked left-to-right, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (404) before any identifier to its right is examined.
4. **State** — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (409).
5. **Prerequisite** — the learn-to-skate prerequisite check, else `ERR_PREREQUISITE_NOT_MET` (422).
6. **Temporal overlap** — the ice-slot resurface-buffer collision (`ERR_SLOT_OVERLAP`, 409) or the locker season-range collision (`ERR_LOCKER_OCCUPIED`, 409).
7. **Capacity and inventory** — capacity, roster, locker-index, and rental-skate limits, yielding `ERR_CAPACITY_FULL` (409) or, for rental skates specifically, `ERR_NO_RENTAL_SKATES` (409).
8. **Fiscal** — sufficient wallet credit for the charge, else `ERR_INSUFFICIENT_FUNDS` (402).
9. **Optimistic concurrency** — the tuition subscription version match, else `ERR_STALE_VERSION` (412).
10. **Field-level validity** — required fields present, enums valid, end after start, non-negative amounts, and pagination within range, else `ERR_INVALID_REQUEST` (400).

This ordering is significant: for example, a mid-flight state problem surfaces as `ERR_INVALID_STATE` before any capacity or fiscal check runs, and an ownership violation surfaces as `ERR_UNAUTHORIZED` before existence is confirmed.

## 3. Business Logic & Workflows

### 3.1. Rinks and the Ice-Slot Schedule

A rink is the top-level facility resource, created by a `RinkManager` with a display `name`, a `resurface_buffer_minutes` value (the Zamboni buffer, at least 0, that must separate two ice slots on this rink), and a battery of operating parameters. Two of those parameters bound the day: `open_hour_utc` (the hour of day, 0–23 UTC, at or after which slots may start; default 6) and `close_hour_utc` (the hour at or before which slots must end; default 23). A third, `peak_start_hour_utc` (default 16), marks the boundary between off-peak and peak rental pricing — a rental beginning at or after this hour is priced at the peak rate, and one beginning before it at the off-peak rate. The rink also declares `public_skate_capacity` (at least 1, the ceiling on simultaneously admitted skaters for any public-skate slot), `public_skate_fee_cents` (at least 0, the per-admission wallet charge), `rental_skate_count` (at least 0, total pairs of rental skates owned), `locker_count` (at least 0, so `locker_number` ranges from 1 through this value), and `locker_fee_cents` (at least 0, charged when a locker is assigned). When a rink is read, two derived figures accompany it: `available_rental_skates` and `available_lockers`, computed as described in §3.2 and §3.5 respectively.

An ice slot is created against a rink in `DRAFT` status. Its `rink_id` names the owning rink, its `purpose` is one of `PUBLIC_SKATE`, `LEARN_TO_SKATE`, `LEAGUE`, `RENTAL`, `BROOMBALL`, or `PARTY`, and its `start_utc` (inclusive) and `end_utc` (exclusive) bound the block of ice; `end_utc` must be strictly after `start_utc` or the create is malformed. A slot's `status` moves among `DRAFT`, `SCHEDULED`, `COMPLETED`, and `CANCELLED`. When a slot is read it also reports `admitted_count` and `available_capacity`, the live figures explained in §3.2.

Publishing a slot advances it from `DRAFT` to `SCHEDULED` and is where the two scheduling guards fire. First, the hours must fit: the UTC hour-of-day of `start_utc` must be at or after the rink's `open_hour_utc`, and the UTC hour-of-day of `end_utc` must be at or before the rink's `close_hour_utc`; otherwise the publish is rejected. Second, the resurface buffer must be respected. For every other non-terminal ice slot on the same rink — that is, every slot still in `DRAFT` or `SCHEDULED`, excluding any that is `COMPLETED` or `CANCELLED` — take that slot's window and widen it by `resurface_buffer_minutes` on each side; the candidate slot's own `[start_utc, end_utc)` window must not overlap any such widened window. A gap exactly equal to the buffer is permitted: adjacency where the untouched slots are separated by precisely the buffer does not overlap and is allowed. Any tighter spacing is a collision, rejected with `ERR_SLOT_OVERLAP`. A successful publish sets `status` to `SCHEDULED` and increments `version`.

Unpublishing reverses a slot from `SCHEDULED` back to `DRAFT` — the schedule is deliberately cyclic between these two states. Because reverting a live slot would strand its dependents, unpublish is permitted only when the slot has no child bookings: there must be zero `PublicSkateAdmission` in `ADMITTED` status, zero non-terminal `LearnToSkateClass`, and zero `SlotBooking` in `BOOKED` status referencing this slot. If any such child exists, the transition is rejected with `ERR_INVALID_STATE`; otherwise `status` returns to `DRAFT` and `version` increments.

Cancelling a slot behaves differently depending on where it starts. A `DRAFT` slot simply moves to `CANCELLED` (a draft has no children to unwind). A `SCHEDULED` slot moves to `CANCELLED` and cascades by purpose: for a `PUBLIC_SKATE` slot, every `ADMITTED` admission becomes `REFUNDED` (crediting the skater's wallet and restoring any rental skate); for a `LEARN_TO_SKATE` slot, every non-terminal class on the slot becomes `CANCELLED`, which withdraws its enrollments and in turn cancels their tuition subscriptions with proration refunds (the full chain is detailed in §3.3 and §3.4); for a `RENTAL`, `BROOMBALL`, or `PARTY` slot, every `BOOKED` booking becomes `CANCELLED`, refunding its `captured_cents` to the host's wallet. The slot's `version` increments. Cancellation carries no precondition — a scheduled slot may always be cancelled.

Completing a slot moves it from `SCHEDULED` to `COMPLETED`, and is gated on time: the logical clock must have reached or passed the slot's `end_utc`, else the request is rejected with `ERR_INVALID_STATE`. On completion of a `PUBLIC_SKATE` slot, every `ADMITTED` admission becomes `EXITED`, which restores its rental skate to inventory and recognizes its `captured_cents` as revenue — the wallet is deliberately **not** credited on exit. Completing a `LEARN_TO_SKATE` slot drives each of its learn-to-skate classes to `COMPLETED`, which completes their active enrollments (see §3.3). The slot's `version` increments.

### 3.2. Public Skate Admissions and Rental Skates

Admitting a skater to a public-skate session is a `FrontDesk` or `Skater` action taken against a specific ice slot; the request supplies the `skater_id` being admitted and an optional `rental_skate` flag (default false) indicating whether a pair of rental skates is issued. The target slot must be a `PUBLIC_SKATE` slot in `SCHEDULED` status — any other purpose or status yields `ERR_INVALID_STATE`.

Capacity is enforced per slot. The slot's `admitted_count` is the number of admissions for that slot currently in `ADMITTED` status, and its `available_capacity` is the rink's `public_skate_capacity` minus that count. An admission is allowed only while `admitted_count` is strictly less than `public_skate_capacity`; when the count has reached capacity, a further admission is rejected with `ERR_CAPACITY_FULL`. When a rental skate is requested, a second inventory check applies: the rink's `available_rental_skates` equals `rental_skate_count` minus the number of `ADMITTED` admissions across all of the rink's slots that carry `rental_skate` set to true. A rental admission is allowed only when `available_rental_skates` is at least 1; if no pairs are free, the admission is rejected with `ERR_NO_RENTAL_SKATES`.

On a successful admission, the rink's `public_skate_fee_cents` is deducted from the skater's wallet and recorded as the admission's `captured_cents`; the admission is created in `ADMITTED` status; `admitted_count` rises by one; and if a rental skate was issued, the available rental-skate figure falls by one. The admission also carries a `refunded_cents` field, which starts at 0. An admission's `captured_cents` reflects the fee while the admission is `ADMITTED` and reads 0 once the admission has become `EXITED` or `REFUNDED`.

An admission may be refunded by a `RinkManager` or `FrontDesk` while it is `ADMITTED`. Refunding credits the admission's `captured_cents` back to the skater's wallet, sets `refunded_cents` to that amount, zeroes `captured_cents`, decrements the slot's admitted count, restores the rental skate if one was issued, and moves the admission to `REFUNDED`. This contrasts with the exit that happens on slot completion, where the same money is instead recognized as revenue and the wallet is not credited.

### 3.3. Learn-to-Skate Classes, Enrollment, and Prerequisites

A learn-to-skate class is created by a `RinkManager` on top of a `LEARN_TO_SKATE` ice slot named by `ice_slot_id`. Each class carries a `level_name` label (for example `SNOWPLOW` or `BASIC_1`), a `capacity` of at least 1 skaters, and an optional `prerequisite_class_id` pointing at the class a skater must have finished before enrolling here (null for an entry-level class). The class exposes `enrolled_count`, the number of its enrollments currently in `ENROLLED` status, and a `status` that is one of `OPEN`, `FULL`, `CANCELLED`, or `COMPLETED`. A class opens in `OPEN`.

The `OPEN`/`FULL` distinction is derived, not directly set. When a new enrollment brings `enrolled_count` up to `capacity`, the class flips from `OPEN` to `FULL`; when a withdrawal drops `enrolled_count` back below `capacity`, it reverts from `FULL` to `OPEN`. These flips are automatic consequences of enrollment count, not separate operations.

Enrolling a skater is a `Skater` or `RinkManager` action supplying the `skater_id`. Three conditions gate it, evaluated in the global order of §2.9. The class must be `OPEN` — enrolling on a `FULL`, `CANCELLED`, or `COMPLETED` class yields `ERR_INVALID_STATE`. If the class declares a `prerequisite_class_id`, the skater must already hold an enrollment with status `COMPLETED` in that prerequisite class; if not, the enrollment is rejected with `ERR_PREREQUISITE_NOT_MET`. Finally the class must have room — `enrolled_count` strictly below `capacity` — or the enrollment is rejected with `ERR_CAPACITY_FULL`. On success the enrollment is created in `ENROLLED` status, `enrolled_count` rises by one, and the class flips to `FULL` if the new count equals `capacity`. Each enrollment records its `class_id` and `skater_id`, and its `status` is one of `ENROLLED`, `COMPLETED`, or `WITHDRAWN`.

An enrollment leaves `ENROLLED` in one of two directions. Withdrawing it — a `Skater` or `RinkManager` action, also triggered automatically when the parent class is cancelled — moves it to `WITHDRAWN`, decrements the class `enrolled_count`, reverts the class from `FULL` to `OPEN` if the count is now below capacity, and cancels any tuition subscription funding that enrollment (see §3.4), incrementing the enrollment's `version`. Completing it — a `RinkManager` action, also triggered automatically when the parent class completes — moves it to `COMPLETED` and increments `version`; a completed enrollment is what satisfies the prerequisite for downstream classes. When a parent ice slot is cancelled, each non-terminal class on it becomes `CANCELLED` and its `ENROLLED` enrollments become `WITHDRAWN`; when a parent ice slot completes, each such class becomes `COMPLETED` and its `ENROLLED` enrollments become `COMPLETED`.

### 3.4. Recurring Tuition, Billing Cycles, and Proration

A tuition subscription funds a specific enrollment on a recurring monthly basis. Creating one is a `Skater` or `RinkManager` action against the enrollment; the request names the enrollment via `enrollment_id`, sets the recurring `monthly_fee_cents` (at least 0), and describes the current cycle with `billing_cycle_start` (a `YYYY-MM-DD` date, inclusive) and `billing_cycle_end` (a `YYYY-MM-DD` date, exclusive), plus `total_sessions_in_cycle` (at least 1) and an optional `sessions_attended` (default 0) used by session-based proration. The `proration_mode` selects the refund algorithm applied on cancellation and is either `CALENDAR` (the default) or `SESSIONS`. As detailed in §2.6, the request must also carry `expected_enrollment_version` matching the enrollment's current `version`, or it is rejected with `ERR_STALE_VERSION`.

On creation the `monthly_fee_cents` is charged against the skater's wallet (subject to the `ERR_INSUFFICIENT_FUNDS` guard) and recorded as the subscription's `captured_cents`; the subscription begins in `ACTIVE` status. Because a new `ACTIVE` subscription supersedes any prior one on the same enrollment, any existing `ACTIVE` subscription for that enrollment is moved to `CANCELLED` as part of the create, and the parent enrollment's `version` is incremented by one. A subscription's `status` is one of `ACTIVE`, `PAST_DUE`, or `CANCELLED`.

The billing cycle is cyclic between `ACTIVE` and `PAST_DUE`. Advancing the cycle — a `RinkManager` action — is permitted only when the logical clock has reached or passed the subscription's `billing_cycle_end`; otherwise it is rejected with `ERR_INVALID_STATE`. Advancing rolls both `billing_cycle_start` and `billing_cycle_end` forward by one month, sets `status` to `PAST_DUE`, and increments `version`. Paying — a `Skater` or `RinkManager` action — brings a `PAST_DUE` subscription back to `ACTIVE`; it requires that the skater's `wallet_credit_cents` be at least the `monthly_fee_cents`, deducts that fee from the wallet, adds it to `captured_cents`, sets `status` back to `ACTIVE`, and increments `version`.

Cancelling a subscription depends on its current state. Cancelling an `ACTIVE` subscription — a `Skater` or `RinkManager` action, and also the automatic consequence of withdrawing the funded enrollment — computes a proration refund, credits it to the wallet, sets `status` to `CANCELLED`, increments the subscription's own `version`, and also increments the parent enrollment's `version`. Cancelling a `PAST_DUE` subscription pays no refund at all — the cycle has already lapsed unpaid — and simply sets `status` to `CANCELLED`. When an enrollment is withdrawn, each of its subscriptions in `ACTIVE` or `PAST_DUE` status is cancelled following exactly these same rules: the `ACTIVE` ones refund with proration, the `PAST_DUE` ones refund nothing.

The proration refund is computed the moment the cancellation occurs, using the date component of the logical clock as the cancellation date, and it applies only when cancelling from `ACTIVE`. Two variants exist and, given the same fee and cycle, they generally produce different refunds. Under `CALENDAR` mode, let the total number of days in the cycle be the count of days from `billing_cycle_start` up to `billing_cycle_end`, and let the days remaining be the count of days from the cancellation date up to `billing_cycle_end`, floored at zero so a cancellation on or after the cycle end yields no remaining days. The refund is the `monthly_fee_cents` multiplied by days remaining, divided by total days, rounded half-up to whole cents. Under `SESSIONS` mode, let the sessions remaining be `total_sessions_in_cycle` minus `sessions_attended`, floored at zero, and the refund is the `monthly_fee_cents` multiplied by sessions remaining, divided by `total_sessions_in_cycle`, rounded half-up to whole cents. The resulting refund is added to the skater's `wallet_credit_cents`.

### 3.5. Leagues, Registrations, and Season Lockers

A league is created by a `RinkManager` with a `name`, a `sport` of either `HOCKEY` or `FIGURE`, a `season_start` and `season_end` (both `YYYY-MM-DD` dates), and a `roster_capacity` of at least 1. It reports `roster_count`, the number of its registrations currently in `ACTIVE` status, and moves through `status` values `REGISTRATION_OPEN` (the initial state), `IN_SEASON`, and `CANCELLED`. Starting a league — a `RinkManager` action — moves it from `REGISTRATION_OPEN` to `IN_SEASON` and closes registration; no further registrations are accepted once the season is underway. Cancelling a league — permitted from either `REGISTRATION_OPEN` or `IN_SEASON` — moves it to `CANCELLED` and cascades: every `ACTIVE` registration becomes `CANCELLED`, and each cancelled registration in turn releases its associated locker (below).

Registering a skater is a `Skater` or `RinkManager` action against a league that must still be in `REGISTRATION_OPEN`; registering on an `IN_SEASON` or `CANCELLED` league yields `ERR_INVALID_STATE`. The request supplies the `skater_id` and may optionally reserve a locker by supplying a `rink_id` naming the rink that owns the locker, together with a `locker_number`, a `season_start_date`, and a `season_end_date`. The registration is created in `ACTIVE` status, carrying its `league_id` and `skater_id`; its `status` is one of `ACTIVE` or `CANCELLED`; and `roster_count` rises by one. Registration is capped by the roster: it is allowed only while `roster_count` is strictly below `roster_capacity`, and a full roster yields `ERR_CAPACITY_FULL`. When a `locker_number` is provided, a `rink_id` must accompany it (a `locker_number` supplied without a `rink_id` is rejected with `ERR_INVALID_REQUEST`), and the server additionally creates a locker assignment as a side effect at the named rink, with its `league_registration_id` set to this registration, charging that rink's locker fee and reducing that rink's available lockers as described below. The `rink_id` is a request-only input used to bind and price the locker; it is not persisted on the registration resource.

A locker assignment reserves a numbered locker at a rink for a date range. It may be created directly — a `Skater` or `RinkManager` action against a rink — or as the league-registration side effect just described. A direct request supplies the `skater_id`, the `locker_number`, the `season_start_date` (inclusive) and `season_end_date` (exclusive), and an optional `size` of either `STANDARD` (the default) or `TALL`. The assignment carries its `rink_id`, its optional `league_registration_id` (null when created directly rather than through a registration), and a `status` of `ACTIVE` or `RELEASED`. The chosen `locker_number` must lie between 1 and the rink's `locker_count` inclusive; an index outside that range is rejected with `ERR_CAPACITY_FULL`. The date range must also be clear: for the same rink and the same `locker_number`, the requested `[season_start_date, season_end_date)` half-open interval must not overlap any existing `ACTIVE` assignment's interval. Adjacency is allowed — if an existing assignment ends exactly on the requested start date, there is no overlap — but any true overlap is rejected with `ERR_LOCKER_OCCUPIED`. Once overlap is cleared, the rink's `locker_fee_cents` is charged to the skater's wallet and the assignment is created, reducing `available_lockers`. A rink's `available_lockers` equals its `locker_count` minus the number of distinct `locker_number` values among that rink's `ACTIVE` locker assignments.

Releasing a locker — a `Skater` or `RinkManager` action, and also the automatic consequence of a league registration being cancelled — moves the assignment from `ACTIVE` to `RELEASED`, recomputes the rink's available-locker figure so that this locker number frees up, and increments `version`. The league-cancellation cascade reaches lockers precisely this way: cancelling a league cancels each `ACTIVE` registration, and any `ACTIVE` locker assignment whose `league_registration_id` names that registration is released, restoring the rink's availability.

### 3.6. Private Bookings: Rentals, Broomball, and Parties

A slot booking reserves a whole ice slot for a private use — a rental, a broomball match, or a party. It is created by a `Skater` or `RinkManager` against a specific ice slot named by `ice_slot_id`, with the host identified by `skater_id` and the kind selected by `booking_type`, which is one of `PRIVATE_RENTAL`, `BROOMBALL`, or `PARTY`. The booking type must match the ice slot's purpose: a `PRIVATE_RENTAL` booking requires a `RENTAL` slot, a `BROOMBALL` booking requires a `BROOMBALL` slot, and a `PARTY` booking requires a `PARTY` slot; a mismatch yields `ERR_INVALID_STATE`. The booking's `status` is one of `BOOKED`, `COMPLETED`, or `CANCELLED`, and it opens in `BOOKED`. Every booking exposes a `quoted_cents` (the provisional charge computed at booking), a `final_cents` (the settled charge, 0 until the booking is completed), and a `captured_cents` (the amount actually held against the wallet). At booking time the `quoted_cents` is computed, deducted from the host's wallet subject to the `ERR_INSUFFICIENT_FUNDS` guard, and stored as `captured_cents`.

For a private rental or broomball booking, the quote is a tiered, per-hour calculation. The `includes_resurface` flag (default false) indicates whether a resurfacing surcharge is added. First, take the slot's duration in hours as the difference between its `end_utc` and `start_utc` expressed in hours. The applicable hourly rate is chosen by peak tier: if the slot's `start_utc` hour is at or after the rink's `peak_start_hour_utc`, the rate is the peak rate of 20,000 cents per hour (200 dollars); otherwise it is the off-peak rate of 12,000 cents per hour (120 dollars). The base charge is that rate multiplied by the number of hours, rounded half-up to whole cents. If the booking's host is a `MEMBER`, a member discount of ten percent of the base is computed and rounded half-up to whole cents; a `NON_MEMBER` gets no discount. A broomball booking adds a fixed equipment fee of 5,000 cents (50 dollars); a private rental adds none. If `includes_resurface` is set, a resurfacing surcharge of 4,000 cents (40 dollars) is added. The quoted charge is then, in this exact order, the base minus the discount plus the broomball equipment fee plus the resurfacing surcharge, with the base and discount each rounded before the sum is taken.

A party booking is priced quite differently and uses only its party-specific inputs: a flat `base_fee_cents` (default 0), a pre-tax `per_guest_cents` (default 0), a `guest_count_booked` (default 0) declared at booking, a `guest_count_final` (default 0) recorded at completion, and a `tax_rate` (default 0, for example 0.05). The charge for a given headcount is computed by first taking the tax on a single guest — the `per_guest_cents` multiplied by the `tax_rate`, rounded half-up to whole cents — and adding it to the `per_guest_cents` to form a per-guest total that already includes tax. The charge is then the `base_fee_cents` plus that per-guest total multiplied by the headcount. Tax is therefore rounded once per guest line and then summed across guests — never summed first and taxed after. At booking, this charge is computed on `guest_count_booked` and stored as the provisional `quoted_cents`; at completion it is recomputed on `guest_count_final` to yield `final_cents`, which differs from the provisional whenever the headcount changed.

Completing a booking — a `RinkManager` action — is permitted only once the logical clock has reached or passed the booked slot's `end_utc`, else `ERR_INVALID_STATE`. For a party, completion recomputes `final_cents` from the supplied `guest_count_final` using the party charge above, and the wallet is adjusted by the difference between `final_cents` and the previously captured amount (a positive difference charges more, a negative one refunds), after which `captured_cents` is set equal to `final_cents`. For a private rental or broomball booking, no headcount changes, so `final_cents` simply equals the original `quoted_cents`. Completion sets `status` to `COMPLETED` and increments `version`. Cancelling a booking — a `Skater` or `RinkManager` action from `BOOKED` — refunds the full `captured_cents` back to the host's wallet, zeroes `captured_cents`, sets `status` to `CANCELLED`, and increments `version`.

### 3.7. The Skate-Sharpening Queue

A sharpening order is a walk-up job submitted by a `Skater` or a `FrontDesk` operator. It records the `skater_id`, the `skate_type` (one of `HOCKEY`, `FIGURE`, or `GOALIE`), and a flat `price_cents` (at least 0). Its `status` progresses through `RECEIVED` (the initial state), `IN_PROGRESS`, `READY`, and `PICKED_UP`, and it reports a live `queue_position`.

The `queue_position` is a one-based rank among the orders that are still live — those in `RECEIVED` or `IN_PROGRESS` status — ordered strictly by `created_at` ascending, with ties broken by `created_at` alone and never by `id`. Orders that are `READY` or `PICKED_UP` are excluded and occupy no position. Advancing an order is exclusively a `FrontDesk` action that moves it one step along the chain: `RECEIVED` to `IN_PROGRESS`, then to `READY`, then to `PICKED_UP`, incrementing `version` each time. The step that matters for the queue is the move to `READY`: at that point the order leaves the live queue, and the `queue_position` of every later `RECEIVED` or `IN_PROGRESS` order is recomputed so the line closes up behind it.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that read a resource, or that modify or transition an existing resource, return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1. Request bodies, response bodies, and side effects are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | RinkManager |
| POST | `/rinks` | Create a rink | RinkManager |
| GET | `/rinks/{id}` | Fetch a rink (includes available_rental_skates, available_lockers) | RinkManager, FrontDesk, Skater |
| POST | `/skaters` | Register a skater | RinkManager, FrontDesk |
| GET | `/skaters/{id}` | Fetch a skater (includes wallet_credit_cents) | RinkManager, FrontDesk, Skater |
| POST | `/skaters/{id}/wallet/adjustments` | Admin wallet credit/debit | RinkManager |
| POST | `/ice-slots` | Create an ice slot in DRAFT | RinkManager |
| GET | `/ice-slots/{id}` | Fetch an ice slot (includes admitted_count, available_capacity) | RinkManager, FrontDesk, Skater |
| GET | `/ice-slots` | List ice slots (filter by rink_id, purpose, status) | RinkManager, FrontDesk, Skater |
| POST | `/ice-slots/{id}/publish` | Publish DRAFT to SCHEDULED | RinkManager |
| POST | `/ice-slots/{id}/unpublish` | Revert SCHEDULED to DRAFT | RinkManager |
| POST | `/ice-slots/{id}/cancel` | Cancel a slot; cascade by purpose | RinkManager |
| POST | `/ice-slots/{id}/complete` | Complete a slot after its end time | RinkManager |
| POST | `/ice-slots/{id}/admissions` | Admit a skater to a public-skate slot | FrontDesk, Skater |
| GET | `/admissions/{id}` | Fetch an admission | RinkManager, FrontDesk, Skater |
| GET | `/admissions` | List admissions (filter by ice_slot_id, skater_id, status) | RinkManager, FrontDesk, Skater |
| POST | `/admissions/{id}/refund` | Refund an ADMITTED admission | RinkManager, FrontDesk |
| POST | `/learn-to-skate-classes` | Create a learn-to-skate class | RinkManager |
| GET | `/learn-to-skate-classes/{id}` | Fetch a class (includes enrolled_count) | RinkManager, FrontDesk, Skater |
| GET | `/learn-to-skate-classes` | List classes (filter by ice_slot_id, prerequisite_class_id) | RinkManager, FrontDesk, Skater |
| POST | `/learn-to-skate-classes/{id}/enrollments` | Enroll a skater | Skater, RinkManager |
| GET | `/enrollments/{id}` | Fetch an enrollment | RinkManager, FrontDesk, Skater |
| GET | `/enrollments` | List enrollments (filter by class_id, skater_id, status) | RinkManager, FrontDesk, Skater |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment | Skater, RinkManager |
| POST | `/enrollments/{id}/complete` | Complete an enrollment | RinkManager |
| POST | `/enrollments/{id}/tuition-subscriptions` | Create a recurring tuition subscription | Skater, RinkManager |
| GET | `/tuition-subscriptions/{id}` | Fetch a subscription | RinkManager, FrontDesk, Skater |
| GET | `/tuition-subscriptions` | List subscriptions (filter by enrollment_id, status) | RinkManager, FrontDesk, Skater |
| POST | `/tuition-subscriptions/{id}/advance-cycle` | Roll the billing cycle forward | RinkManager |
| POST | `/tuition-subscriptions/{id}/pay` | Pay a past-due subscription | Skater, RinkManager |
| POST | `/tuition-subscriptions/{id}/cancel` | Cancel a subscription | Skater, RinkManager |
| POST | `/leagues` | Create a league | RinkManager |
| GET | `/leagues/{id}` | Fetch a league (includes roster_count) | RinkManager, FrontDesk, Skater |
| POST | `/leagues/{id}/start` | Begin the season | RinkManager |
| POST | `/leagues/{id}/cancel` | Cancel a league; cascade to registrations and lockers | RinkManager |
| POST | `/leagues/{id}/registrations` | Register a skater; optionally reserve a locker | Skater, RinkManager |
| GET | `/league-registrations/{id}` | Fetch a league registration | RinkManager, FrontDesk, Skater |
| GET | `/league-registrations` | List registrations (filter by league_id, skater_id, status) | RinkManager, FrontDesk, Skater |
| POST | `/rinks/{id}/locker-assignments` | Assign a locker for a season | Skater, RinkManager |
| GET | `/locker-assignments/{id}` | Fetch a locker assignment | RinkManager, FrontDesk, Skater |
| GET | `/locker-assignments` | List locker assignments (filter by rink_id, skater_id, league_registration_id, status) | RinkManager, FrontDesk, Skater |
| POST | `/locker-assignments/{id}/release` | Release a locker | Skater, RinkManager |
| POST | `/ice-slots/{id}/slot-bookings` | Book a slot for rental / broomball / party | Skater, RinkManager |
| GET | `/slot-bookings/{id}` | Fetch a slot booking | RinkManager, FrontDesk, Skater |
| GET | `/slot-bookings` | List slot bookings (filter by ice_slot_id, skater_id, booking_type, status) | RinkManager, FrontDesk, Skater |
| POST | `/slot-bookings/{id}/complete` | Complete a booking after slot end | RinkManager |
| POST | `/slot-bookings/{id}/cancel` | Cancel a booking; refund captured_cents | Skater, RinkManager |
| POST | `/sharpening-orders` | Submit a skate-sharpening order | Skater, FrontDesk |
| GET | `/sharpening-orders/{id}` | Fetch a sharpening order (includes queue_position) | RinkManager, FrontDesk, Skater |
| GET | `/sharpening-orders` | List sharpening orders (filter by skater_id, status) | RinkManager, FrontDesk, Skater |
| POST | `/sharpening-orders/{id}/advance` | Advance one step through the sharpening lifecycle | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_LOCKER_OCCUPIED` | 409 Conflict |
| `ERR_CAPACITY_FULL` | 409 Conflict |
| `ERR_NO_RENTAL_SKATES` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
