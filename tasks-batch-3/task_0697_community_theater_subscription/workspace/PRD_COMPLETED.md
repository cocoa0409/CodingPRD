# Community Theater Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Community Theater Subscription API, the operational backbone of a regional performing-arts organization that sells season subscriptions, single tickets, and flex-pass exchanges while also running its donor program, seat-naming campaigns, and casting workflow. The organization's box office must reconcile three competing pressures at once: a finite, physical seat inventory that has to be reserved, held, committed, and released cleanly across every performance; a tiered pricing model that blends full-season subscription repricing with demand-driven single-ticket pricing and donor-loyalty discounts; and a calendar of show-runs whose renewal windows, on-sale moments, and will-call cutoffs are all governed by time rather than by ad-hoc human judgment.

The API treats the season as a recurring cycle. Subscribers who held seats last year are offered the same seats during a renewal window before those seats are released to single-ticket sale, and the system must guarantee that no seat is ever double-promised across that boundary. Layered on top of ticketing is a patron-relationship program in which fulfilled donations accumulate toward donor levels that, in turn, discount future ticket purchases, and in which a sufficiently generous gift can name a physical seat in perpetuity. Cancellations anywhere in this structure — a cancelled performance, a cancelled subscription, an exchanged ticket — must flow through to refunds, account credit, and seat releases without leaking inventory or money. To keep the benchmark deterministic, the server runs on a logical clock that operators advance explicitly rather than reading wall-clock time, so every time-gated rule can be exercised reproducibly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that govern every endpoint in the API. The entire API is mounted under the `/box-office` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled precisely as follows: `SeasonAdmin`, `BoxOfficeAgent`, `Patron`, and `ArtisticDirector`. When a syntactically valid role is not permitted to perform the requested operation — or when an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

A `SeasonAdmin` configures the season's structure: seasons, productions, venues, seats, and performances, and they alone run the renewal-window transitions and performance scheduling and cancellation. A `BoxOfficeAgent` handles day-to-day commerce: opening, suspending, and settling performance sales, activating and offering renewal on subscriptions, taking payments and will-call pickups, fulfilling and refunding donations, and completing or denying exchanges. An `ArtisticDirector` manages the casting pipeline — creating auditions and recording, calling back, casting, and declining applicants — and shares production creation and announcement with `SeasonAdmin`. A `Patron` is a member of the public acting on their own account.

The header `X-User-ID` is interpreted differently depending on the role. When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron` entity; any ownership check on a resource that references a patron compares that resource's patron foreign key (for example, the `patron_id` on a subscription, ticket, or donation) against `X-User-ID`, and a mismatch yields `ERR_UNAUTHORIZED`. When `X-User-Role` is `SeasonAdmin`, `BoxOfficeAgent`, or `ArtisticDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id` when deciding ownership. All four roles may read resources within their remit.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0. A `limit` or `offset` that is not an integer, or that falls outside its permitted range, is rejected with `ERR_VALIDATION`. Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order, with ties (equal `created_at`) broken by `id` ascending. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set and `has_more` is true exactly when `offset` plus `limit` is strictly less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource in this system — `Season`, `Production`, `Venue`, `Seat`, `Performance`, `Patron`, `Subscription`, `SubscriptionSeat`, `Ticket`, `Donation`, `Exchange`, and `Audition` — carries a server-managed `id` that is a UUID with no type prefix; it is identity only and is minted by the server, never supplied by the client. Each of these resources also carries a `created_at` timestamp in ISO 8601 UTC form with three fractional digits, fixed at creation. Because every entity in this domain participates in mutation, each also carries an `updated_at` timestamp, refreshed on every change, and an integer `version` that begins at the resource's creation and increments by one on each mutation. The `version` field underpins the optimistic-concurrency protocol described in §2.7. Most resources also expose a `status` field whose lifecycle is governed by the state machines described throughout §3; the exact enumerated values for each entity's `status` are given in those workflow narratives.

### 2.5. The Logical Clock and Time-Gated Operations

The server does not read wall-clock time. Instead it maintains a single logical clock that operators set explicitly through an administrative test-driving capability that accepts a target instant `to_iso8601` and reports the new `now_utc`. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is set it stays at that default and never falls back to real time. Several operations are gated on this clock, and each gate, when unsatisfied, has its own rejection code: renewal cannot open until the clock reaches the season's renewal-open instant and cannot close until it reaches the renewal-close instant (both rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`); a performance cannot go on sale, and single tickets cannot be held or paid, before the on-sale instant or while the performance is not selling (`ERR_PERFORMANCE_NOT_ON_SALE`); a will-call pickup is barred once the clock is within the cutoff window before curtain (`ERR_WILL_CALL_CLOSED`); and a performance cannot be settled before its curtain time (`ERR_SETTLE_BEFORE_CURTAIN`). A separate administrative sweep capability scans for expired holds; it is described alongside the ticket lifecycle in §3.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts in this system are integer counts of cents — base subscription fees, ticket face prices, donation amounts, exchange fees, account credit, and every computed total. There are no fractional cents and no floating-point currency anywhere in a response body. Wherever a calculation multiplies a cent amount by a fractional factor (a demand multiplier, a tier weight, a donor discount, or a renewal discount), the result is reduced to an integer by truncating toward zero — that is, by taking the floor — at the precise point each calculation specifies. The individual calculations in §3 state exactly where their floor boundaries fall, because the order of flooring relative to summation changes the result and is a fixed part of the contract.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent entity's `version`, and only these two. The first is subscription activation: a request to activate a subscription must carry `expected_season_version`, and the server compares it against the bound `Season`'s current `version`. If another activation has already drawn renewable seats from that season and advanced its `version` since the client last read it, the client's view of which seats remain claimable is stale and the activation is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412). The second is holding a single ticket: a hold request must carry `expected_performance_version`, compared against the target `Performance`'s current `version`. If a prior hold has legitimately claimed inventory and advanced the performance's `version` since the client last observed it, the client's view of `available_seat_count` is stale and the new hold is rejected with `ERR_STALE_PERFORMANCE_VERSION` (HTTP 412). The `expected_season_version` and `expected_performance_version` fields are non-optional on their respective operations. No other endpoint accepts a version field, and no other endpoint performs a stale-version check.

### 2.8. Inventory, Cascades, and Hierarchical Consistency

Seat inventory on a performance is always derived, never directly written. Whenever a ticket's `fulfillment_status` changes, the system recomputes the four inventory figures on the bound performance: `held_seat_count` is the number of tickets there in `HELD` fulfillment; `sold_seat_count` is the number in `ISSUED` or `COLLECTED` fulfillment; `available_seat_count` is the performance `capacity` minus `held_seat_count` minus `sold_seat_count`, and is never allowed to fall below zero (it is floored at zero); and `gross_sales_cents` is the sum of `price_cents` over all tickets on the performance whose `payment_status` is `PAID`. Tickets in `EXCHANGED` or `VOID` fulfillment are excluded from the held and sold counts.

When an operation mutates a resource, that mutation refreshes the resource's `updated_at` and increments its `version`. Several operations in this domain cascade across more than one entity — a cancelled performance refunds tickets and releases subscription seats, a confirmed renewal flips reserved seats to assigned, a closed renewal window releases unrenewed seats — and in every such case each affected entity is independently mutated, with its own `updated_at` and `version` advanced. The precise cascade chains are described in the workflow narratives of §3. The system reconciles these derived figures and parent-child states immediately and synchronously as part of the triggering request; there is no deferred or eventual settling.

### 2.9. Nested Reference Validation Order

Although resources in this domain are peers linked by foreign-key fields in the request body rather than by deep URL nesting, many operations still reference several resources at once — a ticket hold names a performance, a seat, and a patron; an exchange names an original ticket, a target performance, and a target seat. Existence of every referenced resource is validated before any business rule runs, and references are checked left to right: the first identifier that does not resolve to an existing resource determines the rejection, each with its own not-found code (`ERR_SEASON_NOT_FOUND`, `ERR_PRODUCTION_NOT_FOUND`, `ERR_PERFORMANCE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_EXCHANGE_NOT_FOUND`, or `ERR_AUDITION_NOT_FOUND`). There is no dedicated subscription-seat not-found code: a `SubscriptionSeat` that does not resolve — whether named by a path id on the subscription-seat read endpoint or referenced in a body — is reported with `ERR_SEAT_NOT_FOUND`.

### 2.10. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. The order is: (1) presence and well-formedness of the `X-User-ID` and `X-User-Role` headers, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization, including ownership for the `Patron` role, failing with `ERR_UNAUTHORIZED`; (3) existence of every referenced resource, checked left to right per §2.9, failing with the matching not-found code; (4) that the target resource is in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE`; (5) the time-window gates of §2.5; (6) seat and accessibility constraints, covering `ERR_SEAT_NOT_IN_VENUE`, `ERR_SEAT_ALREADY_TAKEN`, `ERR_ACCESSIBILITY_UNAVAILABLE`, and `ERR_SEAT_NOT_RENEWABLE`; (7) referential business rules, covering `ERR_SEAT_ALREADY_NAMED`, `ERR_TARGET_SEAT_MISMATCH`, and `ERR_ROLE_ALREADY_CAST`; (8) fiscal capacity and credit limits, covering `ERR_PERFORMANCE_SOLD_OUT` and `ERR_INSUFFICIENT_CREDIT`; and (9) the optimistic-concurrency stale-version checks of §2.7, failing with `ERR_STALE_SEASON_VERSION` or `ERR_STALE_PERFORMANCE_VERSION`. A request body that omits a required field or supplies a wrong type or out-of-range value is rejected with `ERR_VALIDATION`. Earlier checks always mask later ones: an unauthorized caller targeting a nonexistent resource sees `ERR_UNAUTHORIZED`, not a not-found code.

## 3. Business Logic & Workflows

### 3.1. Building the Season Skeleton

A `SeasonAdmin` lays the groundwork by creating a `Season`, supplying its `name`, the `renewal_window_opens_at` and `renewal_window_closes_at` instants, the `base_subscription_fee_cents` (the per-seat full-season base price before any tier weighting or discount, which must be at least zero), and optionally a `loyalty_renewal_discount_pct` — the fractional discount granted to a renewing subscriber, which defaults to 0.10 and must be at least zero and strictly less than one. A new season starts in `PLANNING`, and its `released_seat_count`, the running count of subscription seats released for this season, begins at zero.

Productions hang off a season. Creating a `Production` requires the `season_id` it belongs to and a `title`, and optionally an `accessibility_offered` list naming which services the production can stage; each entry must be drawn from `ASL`, `AUDIO_DESCRIPTION`, or `OPEN_CAPTION`, and the list defaults to empty. A production starts in `DRAFT`. Announcing it, an action a `SeasonAdmin` or `ArtisticDirector` may perform, advances it from `DRAFT` to `ANNOUNCED`, which is the terminal state and which makes the production eligible to back a scheduled performance.

Venues and their seats are pure configuration. A `SeasonAdmin` creates a `Venue` with a `name`; its `total_seat_count` is derived and starts at zero. Each physical `Seat` is created against a `venue_id` with a `section`, a `row_label`, a `seat_number` (at least 1), and a `price_tier` of `PREMIUM`, `STANDARD`, or `VALUE` that selects the base price band; an optional `is_accessible` flag marks wheelchair-accessible or companion seats and defaults to false. Creating a seat increments the bound venue's `total_seat_count`. A seat begins with `naming_status` of `UNNAMED` and a null `named_plaque_text`; both change only when a seat-naming donation is fulfilled, as described in §3.6.

### 3.2. Scheduling Performances and Running the Sales Calendar

A `Performance` is a single show-run instance. A `SeasonAdmin` creates it against a `production_id` and a `venue_id`, with a `starts_at` curtain time and an `on_sale_at` instant; the optional `will_call_cutoff_minutes` (the number of minutes before curtain after which will-call pickup is barred, at least zero, defaulting to 30) and the optional `demand_multiplier` (the dynamic-pricing demand factor, defaulting to 1.0 and constrained to at least 0.5 and at most 3.0) round out the creation payload. A new performance is in `DRAFT`, and its inventory fields are not yet meaningful: `capacity` and `available_seat_count` are null until the performance is scheduled, while `held_seat_count`, `sold_seat_count`, and `gross_sales_cents` start at zero.

Scheduling the performance, which a `SeasonAdmin` performs, advances it from `DRAFT` to `SCHEDULED`, but only if the bound production is already `ANNOUNCED` and the bound venue has at least one seat; a schedule attempted from a non-`DRAFT` performance, or while the production is not yet `ANNOUNCED`, or against a venue with no seats, is rejected with `ERR_INVALID_STATE`. At that moment the system snapshots `capacity` as the count of seats in the venue and sets `available_seat_count` equal to that capacity. A `BoxOfficeAgent` then opens sales, moving the performance from `SCHEDULED` to `ON_SALE`, provided the logical clock has reached `on_sale_at`. Sales can be suspended back from `ON_SALE` to `SCHEDULED` and later reopened — this is a deliberate cycle — and while suspended no new single tickets may be held. After curtain, a `BoxOfficeAgent` settles the performance from `ON_SALE` to `SETTLED`, which is permitted only once the clock has reached `starts_at`; settling computes `gross_sales_cents` over the performance's `PAID` tickets and cascades every remaining `HELD` unpaid ticket to `VOID` fulfillment, freeing nothing further to sell. Both `SETTLED` and `CANCELLED` are terminal.

Cancelling a performance is a `SeasonAdmin` action available from `DRAFT`, `SCHEDULED`, or `ON_SALE`, and it drives a three-level cascade. Every non-`VOID` ticket on the performance moves to `VOID` fulfillment. Each such ticket that was `PAID` additionally moves to `REFUNDED` payment, and that refund credits the holder by adding the ticket's `price_cents` to the patron's `account_credit_cents`. Each voided ticket whose `origin` is `SUBSCRIPTION` further flips its associated subscription seat to `RELEASED`. Every entity touched in this cascade — tickets, the patron, and any subscription seats — has its own `updated_at` and `version` advanced.

### 3.3. Subscriptions: Assigning Seats, Activating, and Pricing

Before any of this can happen a patron must exist. A `SeasonAdmin` or `BoxOfficeAgent` registers a `Patron` with a `full_name` and a unique contact `email`; the `email` must be unique among all patrons. A freshly registered patron starts with a `donor_level` of `NONE`, a `lifetime_donation_cents` of zero, and an `account_credit_cents` balance of zero.

A `Subscription` ties a patron to a season. Either a `BoxOfficeAgent` or the owning `Patron` creates one, supplying the `season_id`, the `patron_id`, and optionally a `prior_subscription_id` that points at the prior-season subscription being renewed; when that reference is supplied the subscription's derived `is_renewal` flag is true, and when it is absent (the default of null) the subscription is brand-new. A subscription starts in `DRAFT`. Its derived `seat_count` counts the subscription seats currently in `ASSIGNED` status, and its `total_price_cents` holds the priced total computed at activation.

Renewable seats are attached one at a time. Creating a `SubscriptionSeat` requires the `subscription_id` and the `seat_id` of the physical seat to hold across the season; the new seat starts in `ASSIGNED`, and its `per_seat_price_cents` is filled in only when the subscription is priced. A subscription seat may be in `ASSIGNED`, `RELEASED`, or `RENEWAL_OFFERED` — the last reserving the seat for the prior holder during the renewal window. An attempt to assign a seat that is not in a renewable, assignable condition is rejected with `ERR_SEAT_NOT_RENEWABLE`; concretely, the assignment is rejected only when the same physical `seat_id` is already in `ASSIGNED` status on a different subscription bound to the same season. A `RENEWAL_OFFERED` reservation on another subscription does not block assignment — it is the prior holder's reservation being carried into a successor — and a seat that is only `RELEASED` elsewhere is likewise assignable; another subscription-seat row for the same seat that belongs to a different season never blocks. The newly created subscription seat starts in `ASSIGNED` regardless.

Activation is where pricing happens, and it is an OCC-guarded `BoxOfficeAgent` operation. A subscription may move from `DRAFT` to `ACTIVE` only if it has at least one subscription seat in `ASSIGNED` status and the supplied `expected_season_version` matches the bound season's current `version`; a subscription that is not in `DRAFT`, or that has no `ASSIGNED` subscription seat, is rejected with `ERR_INVALID_STATE`, and a stale version is rejected with `ERR_STALE_SEASON_VERSION` as described in §2.7 (the state and seat checks of priority 4 precede the priority-9 version check, so a `DRAFT` subscription with no assigned seat sees `ERR_INVALID_STATE` even when the version is also stale). On success the system runs subscription pricing and then increments the bound season's `version` by one. Subscription pricing works one seat at a time: for each `ASSIGNED` subscription seat, the per-seat price is the season's `base_subscription_fee_cents` multiplied by the tier weight for that seat's `price_tier` — 1.5 for `PREMIUM`, 1.0 for `STANDARD`, and 0.6 for `VALUE` — then floored to whole cents; if the subscription is a renewal, that floored per-seat figure is further multiplied by one minus the season's `loyalty_renewal_discount_pct` and floored again. Each seat's result is written to its `per_seat_price_cents`. The subscription's `total_price_cents` is the sum of those per-seat figures. The flooring happens per seat first and the floored per-seat amounts are then summed — this is a sum of floors, not a floor of the sum, and the per-seat floor is the pinned rounding boundary.

### 3.4. The Renewal Cycle

The renewal cycle moves a season and its subscriptions through one full loop. A `SeasonAdmin` opens renewal, advancing the season from `PLANNING` to `RENEWAL_OPEN`, but only once the logical clock has reached the season's `renewal_window_opens_at`; opening too early is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. Opening renewal reserves prior holders' seats: for every `ASSIGNED` subscription seat whose owning subscription is bound to this same season and is currently in `ACTIVE` status, the seat is moved to `RENEWAL_OFFERED`, holding it for that prior holder. Subscription seats whose subscription is in any other status are left untouched.

Within the open window a `BoxOfficeAgent` offers renewal on an active subscription, moving it from `ACTIVE` to `RENEWAL_PENDING`, which is permitted only while the bound season is in `RENEWAL_OPEN`; this marks the subscription as eligible to spawn a successor this cycle. The owning `Patron` then confirms the renewal, moving the subscription from `RENEWAL_PENDING` to `RENEWED`, which requires that a successor subscription — one whose `prior_subscription_id` equals this subscription's `id` — already exists in `ACTIVE` status; if the subscription is not in `RENEWAL_PENDING`, or if no such `ACTIVE` successor exists, the request is rejected with `ERR_INVALID_STATE`. Confirming the renewal flips the successor's `RENEWAL_OFFERED` subscription seats to `ASSIGNED` and reprices the successor through subscription pricing with the loyalty renewal discount applied. Alternatively, a `RENEWAL_PENDING` subscription may lapse, moving to the terminal `LAPSED` state either by an explicit `BoxOfficeAgent` action or automatically by the season's renewal-close cascade; a lapsed subscription's `RENEWAL_OFFERED` seats are released by that close cascade.

Closing renewal is the season's next transition: a `SeasonAdmin` moves the season from `RENEWAL_OPEN` to `ON_SALE`, permitted only once the clock has reached `renewal_window_closes_at` (otherwise `ERR_RENEWAL_WINDOW_NOT_OPEN`). The close cascade releases every subscription seat still in `RENEWAL_OFFERED` to `RELEASED` — the prior holder did not renew — and increments the season's `released_seat_count` by one for each such release, freeing those seats for single sale. Finally a `SeasonAdmin` closes the season, moving it from `ON_SALE` to the terminal `CLOSED` state; this is permitted only when every performance under the season's productions is already in `SETTLED` or `CANCELLED`, and a close attempted while the season is not in `ON_SALE` or while any such performance remains in another state is rejected with `ERR_INVALID_STATE`, after which the season is immutable.

A `Patron` may also cancel their own subscription from `DRAFT`, `ACTIVE`, or `RENEWAL_PENDING`, sending it to the terminal `CANCELLED` state. Cancellation releases all of the subscription's `ASSIGNED` and `RENEWAL_OFFERED` subscription seats to `RELEASED` and credits the patron by adding the subscription's `total_price_cents` to their `account_credit_cents`.

### 3.5. Single Tickets: Holding, Paying, Collecting, and Releasing

A `Ticket` carries two independent state dimensions. The `fulfillment_status` axis runs `HELD`, `ISSUED`, `COLLECTED`, and the terminals `EXCHANGED` and `VOID`; the `payment_status` axis runs `UNPAID`, `PAID`, and `REFUNDED`, and it evolves on its own. Both default to the start of their respective axes (`HELD` and `UNPAID`) when a ticket is created.

Either a `BoxOfficeAgent` or a `Patron` holds a ticket by naming the `performance_id`, the `seat_id`, the `patron_id`, the `origin` (`SINGLE` or `SUBSCRIPTION`, which selects the pricing path), and the `expected_performance_version`; a `subscription_id` may be supplied when the ticket is issued from a subscription seat (it defaults to null for a single ticket), and an `accessibility_service` of `NONE`, `ASL`, `AUDIO_DESCRIPTION`, or `OPEN_CAPTION` may name a requested seating service (defaulting to `NONE`). Holding is gated on inventory and seat rules: the requested seat must belong to the performance's venue (else `ERR_SEAT_NOT_IN_VENUE`), must not already carry a non-`VOID` ticket on that performance (else `ERR_SEAT_ALREADY_TAKEN`), and any requested `accessibility_service` other than `NONE` must be present in the production's `accessibility_offered` set (else `ERR_ACCESSIBILITY_UNAVAILABLE`). A single-ticket hold is only valid while the performance is `ON_SALE` (else `ERR_PERFORMANCE_NOT_ON_SALE`), may not exceed `available_seat_count` — that is, it is rejected with `ERR_PERFORMANCE_SOLD_OUT` whenever the performance's current `available_seat_count` is zero or less, and any hold of `origin` `SUBSCRIPTION` is subject to the same on-sale, seat, and capacity gates as a single hold — and is subject to the stale-version check on `expected_performance_version` from §2.7. A successful hold runs single-ticket pricing when the origin is `SINGLE`, sets `fulfillment_status` to `HELD`, computes the `hold_expires_at` instant after which an unpaid hold may be swept — fixed at the current logical clock plus 15 minutes — increments the bound performance's `version` by one, and recomputes performance inventory.

Single-ticket pricing reads the seat's `price_tier`, the performance's `demand_multiplier`, and the patron's `donor_level`. The tier base price — 9000 cents for `PREMIUM`, 6000 cents for `STANDARD`, 3500 cents for `VALUE` — is multiplied first by the demand multiplier to give a demand-adjusted raw amount. Then the donor discount for the patron's level — 0.0 for `NONE`, 0.05 for `FRIEND`, 0.10 for `PATRON`, and 0.20 for `BENEFACTOR` — is applied by multiplying the raw amount by one minus that discount fraction, and the result is floored to whole cents to give `price_cents`. The order is fixed: demand first, then donor discount, then floor. Accessibility services never raise the price; an accessible or companion seat is priced at its own tier band. A `SUBSCRIPTION`-origin ticket instead copies its `price_cents` from the owning subscription seat's `per_seat_price_cents` rather than running this calculation; the owning subscription seat is the one matching the supplied `subscription_id` and the held `seat_id`, and when no `subscription_id` is supplied or no such subscription seat (with a non-null `per_seat_price_cents`) is found, the ticket's `price_cents` is 0.

Paying for a ticket, an action a `BoxOfficeAgent` or `Patron` may take, advances `fulfillment_status` from `HELD` to `ISSUED` while independently moving `payment_status` from `UNPAID` to `PAID`; it is permitted only when the ticket is currently `UNPAID` and the bound performance is `ON_SALE`, and it recomputes the performance's `held_seat_count`, `sold_seat_count`, and `gross_sales_cents`. Will-call pickup is a `BoxOfficeAgent` action that advances a ticket from `ISSUED` to `COLLECTED`; it requires the ticket to be `PAID` and requires the logical clock to be strictly earlier than `will_call_cutoff_minutes` before curtain — that is, the clock must be earlier than the curtain time minus the cutoff (otherwise `ERR_WILL_CALL_CLOSED`). Releasing an unpaid hold, which a `BoxOfficeAgent` or `Patron` may do, moves a still-`UNPAID` ticket from `HELD` to `VOID` and recomputes inventory.

Unpaid holds also expire on their own. The administrative sweep capability scans every `HELD` ticket whose `hold_expires_at` is at or before the current logical clock and whose `payment_status` is `UNPAID`, moves each to `VOID` fulfillment, recomputes the affected performances' inventory, and reports the swept ticket identifiers as `swept_ticket_ids`.

### 3.6. Donations, Donor Levels, and Seat Naming

Either a `BoxOfficeAgent` or a `Patron` pledges a `Donation` by supplying the `patron_id` and an `amount_cents` (at least 1); a seat-naming gift additionally supplies the `seat_id` of the seat to name and the `plaque_text` to engrave, while a plain gift leaves both null. A donation starts in `PLEDGED`. Fulfilling it, a `BoxOfficeAgent` action, advances it from `PLEDGED` to `FULFILLED`; when the donation names a seat, fulfillment requires that seat to be `UNNAMED` (otherwise `ERR_SEAT_ALREADY_NAMED`), and on success it sets the seat's `naming_status` to `NAMED` and copies the donation's `plaque_text` into the seat's `named_plaque_text`. Fulfillment also recomputes the patron's lifetime giving and donor level.

The patron's `lifetime_donation_cents` is the sum of `amount_cents` over that patron's `FULFILLED` donations only — `PLEDGED` and `REFUNDED` gifts are excluded. The derived `donor_level` is set from that lifetime total against ascending thresholds: `BENEFACTOR` when the lifetime total is at least 500000 cents, otherwise `PATRON` when it is at least 100000 cents, otherwise `FRIEND` when it is at least 25000 cents, and otherwise `NONE`. The boundaries are inclusive at the lower edge, so exactly 25000 cents qualifies as `FRIEND` while 24999 cents remains `NONE`. Refunding a fulfilled donation, also a `BoxOfficeAgent` action, advances it from `FULFILLED` to the terminal `REFUNDED` state and removes its `amount_cents` from the lifetime total, recomputing `donor_level`, which may demote the patron; the seat naming, however, is never reverted by a refund.

### 3.7. Exchanges and Flex-Passes

An `Exchange` lets a holder move a paid, issued ticket to a different seat or performance. Either a `BoxOfficeAgent` or a `Patron` requests one by supplying the `original_ticket_id` being exchanged out, the `target_performance_id` the holder wants to move into, the `target_seat_id` requested there, and the `mode` — `FLEX_PASS` or `PAID_EXCHANGE`. A new exchange starts in `REQUESTED`, with its computed `fee_cents`, `price_delta_cents`, and `new_ticket_id` not yet set. A `BoxOfficeAgent` may deny an exchange, moving it from `REQUESTED` to the terminal `DENIED` state and leaving the original ticket untouched, after which the holder may submit a fresh exchange — request and deny form a deliberate cycle across attempts.

Completing an exchange is a `BoxOfficeAgent` action that moves it from `REQUESTED` to the terminal `COMPLETED` state, and it accepts an optional `pay_from_credit` flag. Completion requires the exchange to be in `REQUESTED` status and the original ticket to be in `ISSUED` fulfillment and `PAID` payment (otherwise `ERR_INVALID_STATE`), the target seat to belong to the target performance's venue (otherwise `ERR_TARGET_SEAT_MISMATCH`), the target seat to be free of any non-`VOID` ticket on the target performance (otherwise `ERR_SEAT_ALREADY_TAKEN`), and, when `pay_from_credit` is set, the patron's `account_credit_cents` to be at least the total charge (otherwise `ERR_INSUFFICIENT_CREDIT`); these run in that order, so the original-ticket state check precedes the seat-mismatch, seat-taken, and credit checks. On completion the system computes the exchange fee, moves the original ticket to `EXCHANGED` fulfillment and `REFUNDED` payment, mints a replacement ticket in `ISSUED` fulfillment and `PAID` payment on the target seat — its `price_cents` set to the target seat's single-ticket price for the target performance and patron (the same figure used for the price delta), its `origin` `SINGLE`, its `subscription_id` null, and its `accessibility_service` `NONE` — records that replacement's id as `new_ticket_id`, recomputes inventory on both the original and the target performances, and — when `pay_from_credit` was set — debits the patron's `account_credit_cents` by the total charge.

The exchange fee combines a price delta and a flat fee. The `price_delta_cents` is the target seat's single-ticket price for the target performance and patron (computed exactly as in §3.5) minus the original ticket's `price_cents`, floored at zero so that a cheaper target never yields a credit. The `fee_cents` depends on the mode: for a `PAID_EXCHANGE` it is always 800 cents; for a `FLEX_PASS` it is waived to 0 only when the original ticket's `origin` is `SUBSCRIPTION`, and is otherwise 500 cents when the original ticket is a single-origin ticket. The total charge applied at completion is the `fee_cents` plus the `price_delta_cents`.

### 3.8. Account Credit as a Conserved Ledger

A patron's `account_credit_cents` is a conserved-quantity ledger and is never negative — it is floored at zero. Refunds add to it from two sources: the `price_cents` of each of the patron's tickets whose payment flips from `PAID` to `REFUNDED` by a cancellation, and the `total_price_cents` of each of the patron's cancelled subscriptions. Exchange charges subtract from it whenever an exchange's total charge is paid from credit. Read at any time, the balance equals refunds in minus credit consumed, never dropping below zero; refund-in must equal credit-out plus the residual balance.

### 3.9. Auditions and Casting

The casting pipeline runs independently of ticketing. An `ArtisticDirector` schedules an `Audition` against a `production_id` with an `applicant_name` and a `role_applied_for`; it starts in `SCHEDULED`, with its `cast_role` and `is_volunteer` fields unset (the latter defaulting to false). Recording the audition advances it from `SCHEDULED` to `AUDITIONED`, permitted only while the bound production is in `DRAFT` or `ANNOUNCED`. From `AUDITIONED` the director may issue a callback, advancing it to `CALLBACK`. Casting may be performed from either `AUDITIONED` or `CALLBACK`, advancing the audition to the terminal `CAST` state; the cast action supplies the `cast_role` and an optional `is_volunteer` flag, and it is rejected with `ERR_ROLE_ALREADY_CAST` if any existing `CAST` audition on the same production already holds that same `cast_role`. A successful cast records the `cast_role` and `is_volunteer` on the audition, placing the performer on the cast or volunteer roster. From `SCHEDULED`, `AUDITIONED`, or `CALLBACK`, the director may instead decline the applicant, moving the audition to the terminal `DECLINED` state.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that transition or otherwise modify an existing resource, as well as all reads and the administrative clock operations, return `200 OK`. "Any" in the authorized-role column means all four roles (`SeasonAdmin`, `BoxOfficeAgent`, `Patron`, `ArtisticDirector`) may call the endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/box-office/_clock/set_current_utc` | Set the server logical clock | SeasonAdmin |
| POST | `/box-office/_clock/sweep_holds` | Sweep expired unpaid held tickets to void | SeasonAdmin |
| POST | `/box-office/seasons` | Create a season | SeasonAdmin |
| GET | `/box-office/seasons/{id}` | Get one season | Any |
| GET | `/box-office/seasons` | List seasons | Any |
| POST | `/box-office/seasons/{id}/open-renewal` | Open the renewal window | SeasonAdmin |
| POST | `/box-office/seasons/{id}/close-renewal` | Close renewal; release unrenewed seats | SeasonAdmin |
| POST | `/box-office/seasons/{id}/close` | Close the season | SeasonAdmin |
| POST | `/box-office/productions` | Create a production | SeasonAdmin, ArtisticDirector |
| GET | `/box-office/productions/{id}` | Get one production | Any |
| GET | `/box-office/productions` | List productions | Any |
| POST | `/box-office/productions/{id}/announce` | Announce a production | SeasonAdmin, ArtisticDirector |
| POST | `/box-office/venues` | Create a venue | SeasonAdmin |
| GET | `/box-office/venues/{id}` | Get one venue | Any |
| POST | `/box-office/seats` | Create a physical seat | SeasonAdmin |
| GET | `/box-office/seats/{id}` | Get one seat | Any |
| GET | `/box-office/seats` | List seats | Any |
| POST | `/box-office/performances` | Create a performance | SeasonAdmin |
| GET | `/box-office/performances/{id}` | Get one performance with inventory | Any |
| GET | `/box-office/performances` | List performances | Any |
| POST | `/box-office/performances/{id}/schedule` | Schedule a performance; snapshot capacity | SeasonAdmin |
| POST | `/box-office/performances/{id}/open-sales` | Open single-ticket sales | BoxOfficeAgent |
| POST | `/box-office/performances/{id}/suspend-sales` | Suspend sales | BoxOfficeAgent |
| POST | `/box-office/performances/{id}/settle` | Settle a performance after curtain | BoxOfficeAgent |
| POST | `/box-office/performances/{id}/cancel` | Cancel a performance with cascade | SeasonAdmin |
| POST | `/box-office/patrons` | Register a patron | SeasonAdmin, BoxOfficeAgent |
| GET | `/box-office/patrons/{id}` | Get one patron | SeasonAdmin, BoxOfficeAgent, Patron |
| POST | `/box-office/subscriptions` | Create a subscription | BoxOfficeAgent, Patron |
| GET | `/box-office/subscriptions/{id}` | Get one subscription | SeasonAdmin, BoxOfficeAgent, Patron |
| GET | `/box-office/subscriptions` | List subscriptions | SeasonAdmin, BoxOfficeAgent, Patron |
| POST | `/box-office/subscription-seats` | Assign a renewable seat | BoxOfficeAgent, Patron |
| GET | `/box-office/subscription-seats/{id}` | Get one subscription seat | SeasonAdmin, BoxOfficeAgent, Patron |
| GET | `/box-office/subscription-seats` | List subscription seats | SeasonAdmin, BoxOfficeAgent, Patron |
| POST | `/box-office/subscriptions/{id}/activate` | Activate a subscription; price seats | BoxOfficeAgent |
| POST | `/box-office/subscriptions/{id}/offer-renewal` | Offer renewal | BoxOfficeAgent |
| POST | `/box-office/subscriptions/{id}/confirm-renewal` | Confirm renewal | Patron |
| POST | `/box-office/subscriptions/{id}/cancel` | Cancel a subscription | Patron |
| POST | `/box-office/tickets` | Hold a single ticket or issue from subscription | BoxOfficeAgent, Patron |
| GET | `/box-office/tickets/{id}` | Get one ticket | SeasonAdmin, BoxOfficeAgent, Patron |
| GET | `/box-office/tickets` | List tickets | SeasonAdmin, BoxOfficeAgent, Patron |
| POST | `/box-office/tickets/{id}/pay` | Pay a held ticket | BoxOfficeAgent, Patron |
| POST | `/box-office/tickets/{id}/will-call-pickup` | Collect at will-call | BoxOfficeAgent |
| POST | `/box-office/tickets/{id}/release` | Release an unpaid hold | BoxOfficeAgent, Patron |
| POST | `/box-office/donations` | Pledge a donation | BoxOfficeAgent, Patron |
| GET | `/box-office/donations/{id}` | Get one donation | SeasonAdmin, BoxOfficeAgent, Patron |
| GET | `/box-office/donations` | List donations | SeasonAdmin, BoxOfficeAgent, Patron |
| POST | `/box-office/donations/{id}/fulfill` | Fulfill a donation; name seat | BoxOfficeAgent |
| POST | `/box-office/donations/{id}/refund` | Refund a fulfilled donation | BoxOfficeAgent |
| POST | `/box-office/exchanges` | Request an exchange or flex-pass | BoxOfficeAgent, Patron |
| GET | `/box-office/exchanges/{id}` | Get one exchange | SeasonAdmin, BoxOfficeAgent, Patron |
| GET | `/box-office/exchanges` | List exchanges | SeasonAdmin, BoxOfficeAgent, Patron |
| POST | `/box-office/exchanges/{id}/complete` | Complete an exchange; mint replacement | BoxOfficeAgent |
| POST | `/box-office/exchanges/{id}/deny` | Deny an exchange request | BoxOfficeAgent |
| POST | `/box-office/auditions` | Schedule an audition | ArtisticDirector |
| GET | `/box-office/auditions/{id}` | Get one audition | SeasonAdmin, ArtisticDirector |
| GET | `/box-office/auditions` | List auditions | SeasonAdmin, ArtisticDirector |
| POST | `/box-office/auditions/{id}/record` | Record an audition | ArtisticDirector |
| POST | `/box-office/auditions/{id}/callback` | Issue a callback | ArtisticDirector |
| POST | `/box-office/auditions/{id}/cast` | Cast a performer | ArtisticDirector |
| POST | `/box-office/auditions/{id}/decline` | Decline an applicant | ArtisticDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SEASON_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_PERFORMANCE_NOT_FOUND` | 404 Not Found |
| `ERR_VENUE_NOT_FOUND` | 404 Not Found |
| `ERR_SEAT_NOT_FOUND` | 404 Not Found |
| `ERR_PATRON_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_DONATION_NOT_FOUND` | 404 Not Found |
| `ERR_EXCHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDITION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_PERFORMANCE_NOT_ON_SALE` | 409 Conflict |
| `ERR_WILL_CALL_CLOSED` | 409 Conflict |
| `ERR_SETTLE_BEFORE_CURTAIN` | 409 Conflict |
| `ERR_SEAT_NOT_IN_VENUE` | 409 Conflict |
| `ERR_SEAT_ALREADY_TAKEN` | 409 Conflict |
| `ERR_ACCESSIBILITY_UNAVAILABLE` | 409 Conflict |
| `ERR_SEAT_NOT_RENEWABLE` | 409 Conflict |
| `ERR_SEAT_ALREADY_NAMED` | 409 Conflict |
| `ERR_TARGET_SEAT_MISMATCH` | 409 Conflict |
| `ERR_ROLE_ALREADY_CAST` | 409 Conflict |
| `ERR_PERFORMANCE_SOLD_OUT` | 402 Payment Required |
| `ERR_INSUFFICIENT_CREDIT` | 402 Payment Required |
| `ERR_STALE_SEASON_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PERFORMANCE_VERSION` | 412 Precondition Failed |
