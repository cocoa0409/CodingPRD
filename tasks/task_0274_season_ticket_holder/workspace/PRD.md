# Season Ticket Holder Management API — Product Requirements Document

## 1. Introduction

This document specifies the Season Ticket Holder Management API, the system of record a professional sports franchise uses to sell, service, and settle season-ticket relationships across an entire venue. The platform must reconcile two pressures that normally pull against each other: a finite, physical seat inventory that can never be double-sold, and a flexible commercial layer of full- and partial-season plans, loyalty pricing, installment financing, ticket forwarding and resale, priority-points loyalty, and parking add-ons. Every commercial action ultimately resolves back to a concrete seat in a concrete section for a concrete season window, so the API treats inventory consistency as sacrosanct while still letting the box office, finance, and the holders themselves move quickly.

Three operator populations share the system with deliberately non-overlapping responsibilities. Box office staff manage the venue inventory and the administrative lifecycle of subscriptions; finance staff own the money — installment plans, payments, defaults, and refunds; and the season-ticket holders themselves act only on the subscriptions and transfers they own. Because seat releases, points clawbacks, refunds, and the derived counters that summarize inventory must all stay truthful at every instant, the system performs each cascade atomically within the request that triggers it, never deferring reconciliation to a later sweep.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint. Where a later business-logic section appears to restate one of these rules, that restatement is reinforcement, not contradiction.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. The system recognizes exactly three roles, spelled precisely as `BoxOfficeAgent`, `AccountHolder`, and `FinanceClerk`. If either header is missing, or if `X-User-Role` does not name one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`.

The three roles partition ownership of the domain. A `BoxOfficeAgent` is the inventory and administrative operator: it creates and lists sections, seats, season plans, and parking zones; registers and suspends accounts; creates subscriptions and drives their lifecycle (activation, the relocation begin/confirm/abort cycle, renewal offers, and cancellation); creates seat assignments; completes resales on the marketplace; and exercises the test/admin points-granting capability. A `FinanceClerk` owns the financing side exclusively: creating payment plans, paying installments, and declaring a plan in default. An `AccountHolder` is the season-ticket holder and may accept a renewal offer on its own subscription and create, forward, list, or cancel ticket transfers against seat assignments it owns. Both a `BoxOfficeAgent` and an `AccountHolder` may create parking add-ons; a broad set of read endpoints is shared across roles as described in the endpoint table.

When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. Concretely, a holder may only act on a subscription whose `account_id` equals its `X-User-ID`, and may only act on a seat assignment whose subscription's `account_id` equals its `X-User-ID`; a violation of this ownership chain is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `BoxOfficeAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `FinanceClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order.

List responses surface their paging state in the `meta` object of the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every entity in this system — `Section`, `Seat`, `Account`, `SeasonPlan`, `Subscription`, `SeatAssignment`, `PaymentPlan`, `Installment`, `TicketTransfer`, `ParkingZone`, and `ParkingAddOn` — carries a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp with three fractional digits that is refreshed on every mutation, including mutations that arrive as a cascaded side effect of an operation on some other resource. The `version` field is an integer that starts at 1 and increments by exactly 1 on every mutation; cascaded mutations bump it just as direct ones do. Every entity in this domain carries all four of these fields.

### 2.5. Inventory Counters and Derived-Field Reconciliation

Several fields are not supplied by clients but are continuously derived from the rows around them, and the system must keep them exact at every observable moment. A `Section` exposes `total_seats`, the count of every `Seat` whose `section_id` equals that section's `id` regardless of status, and `available_seats`, the count of those seats whose `status` equals `AVAILABLE`. A `Subscription` exposes `seat_count`, the count of `SeatAssignment` rows whose `subscription_id` equals that subscription's `id` and whose `status` equals `ASSIGNED`, and `locked_price_cents`, the season total described in §3. A `ParkingZone` exposes `active_pass_count`, the count of `ParkingAddOn` rows whose `parking_zone_id` equals that zone's `id` and whose `status` equals `ACTIVE`. Whenever a seat changes allocation status, a seat assignment is created or released, or a parking pass is added or released, the owning counter is reconciled in the same atomic step, and the counter's owning entity has its `updated_at` refreshed and its `version` incremented as a consequence.

### 2.6. Optimistic Concurrency on Subscriptions

Two subscription operations are guarded by optimistic concurrency control because each one is priced or staged against a particular observed version of the subscription, and acting on a stale view would silently overwrite work the client never saw. Beginning a relocation requires the request to carry `expected_subscription_version` holding the client's last observed `version` of the target `Subscription`; if that value does not equal the subscription's current `version` — for example because the subscription has already moved into a superseding relocation or another renewal cycle has advanced its version — the begin is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` at HTTP 412, and no transition occurs. Accepting a renewal offer likewise requires `expected_subscription_version` to match the subscription's current `version`; the price the holder was shown was computed against an earlier version, so if a re-priced offer has since advanced the version, the stale acceptance is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` at HTTP 412. No other endpoint takes a version field, and on endpoints that are not OCC-guarded the system performs no version check.

### 2.7. Monetary and Points Precision

All money in this system is stored and computed as integer cents — there are no fractional currency values anywhere in the model. Where a calculation multiplies by a basis-points rate (basis points express a fraction of 10000, so 10000 basis points is 100%), the rounding discipline for each rule is stated precisely in §3 and must be followed operand-for-operand, because the choice of flooring versus rounding-half-up, and the order in which intermediate values are rounded, changes the final cent. Where a rule calls for rounding to the nearest cent, the system rounds half up. Priority points are whole integers; every factor that feeds the points accrual is itself an integer, so no rounding is involved in points arithmetic.

### 2.8. Path Resolution and Reference Validation

Requests are validated in a fixed priority order so that the same failure always produces the same error. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED` (HTTP 401). Role permission comes next: a known role attempting an operation it is not authorized for yields `ERR_FORBIDDEN` (HTTP 403). The system then resolves every resource identifier named in the URL path, left to right, and rejects the first one that does not exist with `ERR_NOT_FOUND` (HTTP 404). Only then does it confirm that every foreign-key field carried in the request body — including `account_id`, `season_plan_id`, `section_id`, `seat_id`, `subscription_id`, `parking_zone_id`, `recipient_account_id`, and `seat_assignment_id` — points at an existing resource, rejecting the first dangling reference with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404). After references resolve, the system checks that required body fields are present and well-typed, that every enum value falls inside its declared set, and that every integer falls inside its declared range; any violation yields `ERR_INVALID_REQUEST` (HTTP 422). Business-state, ownership, referential, temporal, capacity, eligibility, uniqueness, and concurrency checks follow, in the order their owning rules are introduced across §2.6 and §3, each carrying its own dedicated error as those sections describe.

### 2.9. Terminal States and Illegal Transitions

Each lifecycle has terminal states from which no further transition is legal. A `Subscription` is terminal once `CANCELLED`. A `PaymentPlan` is terminal once it reaches `PAID_IN_FULL`, `DEFAULTED`, or `CANCELLED`. A `TicketTransfer` is terminal once it reaches `FORWARDED`, `SOLD`, or `CANCELLED`. Attempting to drive any resource out of a terminal state is rejected with `ERR_VALIDATION_FROM_TERMINAL` (HTTP 409). More generally, when a transition is requested against a resource whose current state is not a legal source for that transition — activation against a subscription that is not `PENDING`, a relocation confirm against one that is not `RELOCATING`, a sale completion against a transfer that is not `LISTED`, or paying an installment whose plan is not `ACTIVE` or whose installment is not `SCHEDULED` — the request is rejected with `ERR_INVALID_STATE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Building the Venue: Sections, Seats, and Inventory

The inventory layer is owned entirely by the box office. A seating section is created with a human-readable `name` such as "Lower Bowl 101", a price `tier` that must be one of `PREMIUM`, `STANDARD`, or `VALUE`, and a `base_price_cents` figure — the full-season list price per seat in that section, given as a non-negative integer number of cents. A freshly created section reports `total_seats` of zero and `available_seats` of zero; both grow only as seats are added beneath it.

Individual seats are created within a section. A seat names its parent through `section_id`, a `row_label` such as "A", and a `seat_number` that must be at least 1. Because the same physical seat is resold season after season, each seat also carries the season window it is being sold for: an inclusive `season_start_date` and an inclusive `season_end_date`, both ISO 8601 UTC instants. A new seat begins life with `status` of `AVAILABLE`. The act of creating a seat increments its section's `total_seats` and `available_seats` by one apiece, reconciled atomically. Seats may be listed beneath their section as a reverse lookup on `section_id`, and the global seat list may be filtered by `section_id` and by `status`.

### 3.2. Accounts, Loyalty Tiers, and Priority Points

A season-ticket holder is represented by an `Account`, registered by a box office agent with a `full_name` and a contact `email`. The email must be unique across all accounts. An account may optionally declare `consecutive_seasons`, the number of prior consecutive seasons already held; this value must be non-negative, defaults to 0 when omitted, drives the tenure component of points accrual, and may later be adjusted by the box office. On registration the account's `priority_points` balance is 0, its `status` is `ACTIVE`, and its `loyalty_tier` is `BRONZE`.

The `loyalty_tier` is never supplied by a client; it is derived purely from `priority_points`. An account sits at `BRONZE` while its points are below 500, at `SILVER` once its points are at least 500 but still below 1000, and at `GOLD` once its points reach 1000 or more. Because points move whenever a subscription activates, renews, or cancels, the tier is recomputed in the same step the balance changes. An account may be administratively suspended, moving its `status` from `ACTIVE` to `SUSPENDED`; a suspended account cannot have a subscription activated or a renewal accepted against it, as those flows require the holder account to be `ACTIVE`. Subscriptions belonging to an account may be listed as a reverse lookup on `account_id`.

Because natural accrual would take many seasons to push an account across a tier boundary, an administrative test capability lets a box office agent set an account's `priority_points` directly to a supplied value; the account's `loyalty_tier` is recomputed from the new balance in the same step. This capability exists to stage tier-boundary scenarios and otherwise behaves like any other points mutation.

### 3.3. Season Plans and the Subscription Lifecycle

A `SeasonPlan` is a pricing template, created by the box office with a `name` such as "Full Season 2026", a `plan_type` of either `FULL` or `PARTIAL`, a `game_count` that must be at least 1, and a `price_multiplier_bps` in the closed range from 0 to 10000. The multiplier is the basis-points fraction of a section's base price that this plan charges: a `FULL` plan uses 10000 (the whole base price), while a `PARTIAL` plan uses a value below 10000 to prorate the season down to its subset of games. A plan also declares `includes_playoffs`, a boolean defaulting to false that, when true, grants playoff seating and switches the holder onto the playoff variant of points accrual.

A subscription ties an account to a plan. Creating one takes an `account_id` and a `season_plan_id` and yields a `Subscription` in `PENDING` status with `locked_price_cents` of 0, `seat_count` of 0, and `renewal_cycle` of 0. Before it can be activated, the subscription must hold at least one assigned seat (see §3.4). Activation, performed by a box office agent, is legal only while the subscription is `PENDING`, requires the holder `Account` to be `ACTIVE`, and requires at least one `SeatAssignment` in `ASSIGNED` status to exist for it; activation moves the subscription to `ACTIVE`. As part of activation the system prices the seats and accrues loyalty points as described in §3.7 and §3.8, sets `seat_count` to the number of `ASSIGNED` assignments, and sets `locked_price_cents` to the priced season total.

An `ACTIVE` subscription can be offered for renewal by the box office, which moves it from `ACTIVE` to `RENEWAL_OFFERED` and increments its `version`. From `RENEWAL_OFFERED` the holder accepts the offer (the only subscription action an `AccountHolder` performs directly), which requires the subscription to be `RENEWAL_OFFERED`, the holder account to be `ACTIVE`, and the supplied `expected_subscription_version` to match the subscription's current `version` per §2.6; acceptance moves the subscription back to `ACTIVE`. Accepting reprices the season under the holder's current `loyalty_tier`, resetting `locked_price_cents` and each assignment's `assigned_price_cents`; accrues fresh priority points and recomputes the loyalty tier; increments the account's `consecutive_seasons` by 1; increments the subscription's `renewal_cycle` by 1; and increments the subscription's `version`. A subscription's assignments may be listed as a reverse lookup on `subscription_id`, and subscriptions overall may be filtered by `account_id`, `season_plan_id`, and `status`.

### 3.4. Seating a Subscription and Avoiding Window Collisions

Seats are attached to a subscription through a `SeatAssignment`, created by the box office against a `PENDING` subscription with a `subscription_id` and a `seat_id`. A new assignment begins with `status` of `ASSIGNED` and an `assigned_price_cents` of 0 that is filled in at activation pricing. Creating it drives the seat's `status` to `SOLD`, decrements the seat's section `available_seats`, and increments the subscription's `seat_count`. An assignment's `status` is one of `ASSIGNED`, `RELEASED`, or `REASSIGNED`; releases and reassignments arise from cancellation, relocation, and resale flows rather than from a direct edit. Assignments may be listed globally with filters on `subscription_id`, `seat_id`, and `status`, and also as a reverse lookup beneath a subscription.

Before a seat may be assigned — whether as an initial assignment or as a relocation target — the system guards against double-selling the same physical seat into overlapping seasons. The season window of a subscription is the closed interval running from its seat's `season_start_date` through its `season_end_date` inclusive. A seat may not be assigned if it already backs another `ASSIGNED` `SeatAssignment` whose subscription's season window overlaps the new one; because the interval is closed, two windows that merely share an endpoint date count as a collision. A violation is rejected with `ERR_SEAT_WINDOW_CONFLICT` (HTTP 409). This same window check applies to relocation confirmation.

### 3.5. Relocation: the Begin / Confirm / Abort Cycle

Moving a holder to different seats is a staged cycle that a box office agent drives, so that inventory is never touched until the target seats are known and valid. Beginning a relocation is legal only while the subscription is `ACTIVE`, requires the supplied `expected_subscription_version` to match the subscription's current `version` per §2.6, and moves the subscription from `ACTIVE` to `RELOCATING` while incrementing its `version`; no seats change yet. The cycle then resolves one of two ways.

Confirming the relocation carries the chosen `target_seat_ids` and is legal only while the subscription is `RELOCATING`. Every target seat must currently be `AVAILABLE`, and every target seat must share the same season window as the seats being released. Furthermore, a relocation target seat must belong to the same `Section` as the seats being released and share the same season window; if a target sits in a different section or a different window than the released seats, the confirm is rejected with `ERR_SECTION_MISMATCH` (HTTP 422), and the closed-interval window-overlap guard of §3.4 applies to each target as well. On a valid confirm the current `ASSIGNED` assignments are released — their status becomes `REASSIGNED`, their seats return to `AVAILABLE`, and the affected sections' `available_seats` are incremented — while a new `SeatAssignment` is created for each target seat, those seats become `SOLD`, and their sections' `available_seats` are decremented. The season is then repriced, resetting `locked_price_cents` and `seat_count`, and the subscription returns to `ACTIVE` with its `version` incremented once more.

Aborting the relocation is the revert leg: legal only while the subscription is `RELOCATING`, it makes no inventory change at all, restores the subscription to `ACTIVE`, and increments its `version`.

### 3.6. Suspension and Cancellation Cascades

A subscription can be frozen or torn down, and each carries a precise cascade. Suspension is not requested directly; it is a system event raised when the financing plan defaults (see §3.10), moving an `ACTIVE` subscription to `SUSPENDED`. A suspended subscription keeps its seat assignments in place but is frozen: no ticket transfer may be created against it while it is `SUSPENDED`.

Cancellation is performed by a box office agent and is legal from either `ACTIVE` or `SUSPENDED`, ending the subscription in the terminal `CANCELLED` state. The cancellation cascade is atomic and runs in full: every `ASSIGNED` `SeatAssignment` becomes `RELEASED`, each released seat returns to `AVAILABLE` with its section's `available_seats` incremented, and `seat_count` is driven to 0; the priority points that were granted to the account at this subscription's activation and renewals are clawed back by subtracting that granted total from the account's `priority_points`, after which the loyalty tier is recomputed; any `ACTIVE` `PaymentPlan` for the subscription transitions to `CANCELLED`, which voids each of its `SCHEDULED` `Installment` rows to `VOID`; every `ACTIVE` `ParkingAddOn` becomes `RELEASED`, decrementing its zone's `active_pass_count`; and finally the cancellation refund is computed and recorded on the cancelled payment plan as described in §3.11.

### 3.7. Season Pricing

The season price is computed per seat and then summed, and it is recomputed identically at three moments: at activation, at relocation confirm, and at renewal acceptance. For each `ASSIGNED` `SeatAssignment` of the subscription, start from the seat's section `base_price_cents`. Multiply that full price by the plan's `price_multiplier_bps`, divide by 10000, and take the floor of the result to obtain the plan-adjusted price; for a `FULL` plan whose multiplier is 10000 this equals the full base price, while for a `PARTIAL` plan it is prorated downward. Next compute a loyalty discount: multiply the plan-adjusted price by the account's loyalty rate in basis points, divide by 10000, and take the floor; the loyalty rate is 0 basis points for `BRONZE`, 500 basis points for `SILVER`, and 1000 basis points for `GOLD`. Subtract that discount from the plan-adjusted price. The per-seat `assigned_price_cents` is then the larger of this discounted figure and a minimum partial-season floor of 100000 cents — the floor is applied after the loyalty discount, not before. Each seat's `assigned_price_cents` is set to its computed per-seat price, and the subscription's `locked_price_cents` is the sum of those per-seat prices across all `ASSIGNED` assignments.

The two plan variants differ only in how the plan-adjusted figure lands. Under a `FULL` plan the plan-adjusted price equals the full base price and the 100000-cent floor rarely binds, since full-season prices exceed it. Under a `PARTIAL` plan the plan-adjusted price is prorated down by the multiplier, so the 100000-cent floor can bind and raise the per-seat price above the prorated-minus-discount value.

### 3.8. Priority-Points Accrual

Loyalty points are accrued at two moments — when a subscription activates and when a renewal is accepted — and the seat count used is the number of `ASSIGNED` assignments at the instant of that transition. Begin with a base of the seat count multiplied by 100 points per seat. Add a tenure bonus of the account's `consecutive_seasons` multiplied by 50 points per season. The sum of those two is the standard accrual. If the subscription's plan has `includes_playoffs` set to true, add a further playoff bonus of 200 points for each seat (200 multiplied by the seat count) on top of the standard accrual; if the plan does not include playoffs, no playoff term is added. The resulting points earned are added to the account's `priority_points`, and the `loyalty_tier` is recomputed from the new balance. Because the points granted for a subscription are tracked, cancellation can later claw back exactly that granted total, as described in §3.6. All factors here are whole numbers, so the accrual involves no rounding.

### 3.9. Forwarding and Reselling Tickets

A holder may move a seat to someone else through a `TicketTransfer`, created by the holder against a `seat_assignment_id` with a `transfer_type` of either `FORWARD` or `RESALE`. A `FORWARD` gifts the seat to a recipient account at no charge and requires `recipient_account_id` at creation; a `RESALE` lists the seat on the marketplace for a price and requires `listing_price_cents` (a non-negative gross per-seat list price) while leaving `recipient_account_id` to be supplied only when the sale completes. The `listing_price_cents` field must be present for a `RESALE` and must be omitted for a `FORWARD`; supplying it on a forward or omitting it on a resale, like targeting an assignment that is not `ASSIGNED` or whose subscription is not `ACTIVE`, is rejected with `ERR_TRANSFER_NOT_ELIGIBLE` (HTTP 409). A new transfer begins in `PENDING` status with `payout_cents` of 0. A holder may only create a transfer against a seat assignment whose subscription the holder owns; acting on a seat assignment the holder does not own is rejected with `ERR_SECTION_MISMATCH` (HTTP 422). Transfers may be listed with filters on `seat_assignment_id`, `recipient_account_id`, `status`, and `transfer_type`.

The fork resolves through one of two branches, each with its own distinct side-effect set. Executing a forward is legal only while the transfer is `PENDING` and its `transfer_type` is `FORWARD`, the referenced `SeatAssignment` is `ASSIGNED`, that assignment's subscription is `ACTIVE`, and the `recipient_account_id` names an `ACTIVE` account; the transfer moves to `FORWARDED`, the seat assignment is reassigned into the recipient's active subscription context, no money changes hands, and `payout_cents` stays 0. Listing a resale is legal only while the transfer is `PENDING` and its `transfer_type` is `RESALE`, the referenced assignment is `ASSIGNED`, its subscription is `ACTIVE`, and `listing_price_cents` is present and non-negative; the transfer becomes `LISTED` and visible on the marketplace, with no inventory change yet. A `PENDING` or `LISTED` transfer may be cancelled by the holder, moving it to `CANCELLED` with no inventory change.

Completing a resale is the box office's action and is legal only while the transfer is `LISTED`. It carries the buyer's `recipient_account_id`, which must name an `ACTIVE` account. On completion the system computes the seller's payout, sets `payout_cents`, drives the original `SeatAssignment` to `REASSIGNED`, decrements the seller subscription's `seat_count`, and moves the transfer to `SOLD`. The payout is computed from the `listing_price_cents` as the gross. Two fees are deducted: a marketplace fee of 750 basis points of the gross, and a processing fee of 290 basis points of the gross. Each fee is computed independently as gross multiplied by that fee's basis points divided by 10000 and rounded half up to a whole cent, and only then are the two rounded fees subtracted from the gross. The two fees must be rounded separately and summed — the system must not add the two basis-point rates together and round a single combined fee, because that produces a different cent. A `FORWARD` always yields a payout of 0.

### 3.10. Financing: Payment Plans, Installments, Defaults

A finance clerk may finance a subscription's locked season price through a `PaymentPlan`, created against a `subscription_id` with an `installment_count` that must be at least 2 and at most 12. At most one `ACTIVE` payment plan may exist per subscription; a second attempt while one is still active is rejected with `ERR_PAYMENT_PLAN_EXISTS` (HTTP 409). On creation the plan snapshots the subscription's `locked_price_cents` into `total_cents`, sets `amount_paid_cents` to 0, sets `status` to `ACTIVE`, and generates its installment rows by the waterfall below. Plans may be listed as a reverse lookup on `subscription_id` and filtered by `status`.

The installment waterfall partitions the snapshot total deterministically. The total is the snapshotted `total_cents`. The down payment, carried by the installment whose `sequence` is 1, is 2500 basis points of the total — total multiplied by 2500, divided by 10000, rounded half up to a whole cent. Subtract the down payment from the total to get the remaining amount, and let the rest count be the `installment_count` minus 1. The per-installment amount for the middle installments is the floor of the remaining amount divided by the rest count, and the leftover remainder is the remaining amount minus that per-installment amount multiplied by the rest count. Allocation is pinned: `sequence` 1 receives the down payment; sequences 2 through `installment_count` minus 1 each receive the per-installment amount; and the highest sequence, `installment_count`, receives the per-installment amount plus the remainder, so the rounding remainder always lands on the last installment. Each `Installment` belongs to its plan through `payment_plan_id`, begins with `status` of `SCHEDULED`, and carries the computed `amount_cents`. Installments may be listed beneath their plan and fetched individually.

Paying an installment is a finance-clerk action addressed by the plan and the installment's `sequence`, which is supplied as the `seq` path position. It is legal only while the plan is `ACTIVE` and the target installment is `SCHEDULED`; paying drives that installment to `PAID` and adds its `amount_cents` to the plan's `amount_paid_cents`. While scheduled installments remain, the plan stays `ACTIVE`. When the installment being paid is the only remaining `SCHEDULED` one, paying it additionally moves the plan to the terminal `PAID_IN_FULL` state. Declaring a default is also a finance-clerk action, legal only while the plan is `ACTIVE` and at least one installment is still `SCHEDULED`; it moves the plan to `DEFAULTED` and, as a cascade, transitions the financed subscription from `ACTIVE` to `SUSPENDED`, freezing its seat assignments. Separately, when a subscription is cancelled, its `ACTIVE` plan is driven to `CANCELLED` and all that plan's `SCHEDULED` installments are voided to `VOID`, as described in §3.6.

### 3.11. Cancellation Refund

When a subscription is cancelled, the refund recorded on its cancelled payment plan is computed as follows. The paid amount is the plan's `amount_paid_cents`, taken as 0 when no payment plan exists for the subscription. The cancellation fee is 1000 basis points of the subscription's `locked_price_cents` — `locked_price_cents` multiplied by 1000, divided by 10000, rounded half up to a whole cent. The refund is the paid amount minus the fee, floored at 0 so that it is never negative. This figure is recorded on the cancelled plan as its final settlement; when no plan exists, the refund context is 0.

### 3.12. Parking Add-Ons and Zone Capacity

Parking is sold against a zone of finite capacity. A `ParkingZone` is created by the box office with a `name` such as "Lot A", a `capacity` (the maximum number of concurrently `ACTIVE` passes the zone may hold, a non-negative integer), and a `price_cents` season pass price that must be non-negative. A new zone reports `active_pass_count` of 0. A `ParkingAddOn` attaches a pass to a subscription and may be created by either a box office agent or the holder, taking a `subscription_id` and a `parking_zone_id`. At add time the pass snapshots the zone's `price_cents` into its own `price_cents`, begins with `status` of `ACTIVE`, and increments the zone's `active_pass_count`. A pass may not be added when its target zone is already at capacity — that is, when the zone's `active_pass_count` is greater than or equal to its `capacity` — and such an attempt is rejected with `ERR_PARKING_ZONE_FULL` (HTTP 409). Releasing a pass moves its `status` to `RELEASED` and decrements the zone's `active_pass_count`; this happens as part of the cancellation cascade in §3.6. Parking add-ons may be listed globally with filters on `subscription_id`, `parking_zone_id`, and `status`, and also as a reverse lookup beneath a subscription.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or act on an existing resource — including all lifecycle actions and all list and fetch reads — return `200 OK`. The table below is a routing summary only; the request bodies, response shapes, and side effects of each operation are specified in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sections` | Create a seating section | BoxOfficeAgent |
| GET | `/sections/{id}` | Fetch a section with computed inventory counts | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/sections` | List sections | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/sections/{id}/seats` | List seats belonging to a section | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/seats` | Create a seat within a section | BoxOfficeAgent |
| GET | `/seats/{id}` | Fetch a seat | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/seats` | List seats, filterable by section | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/accounts` | Register an account holder | BoxOfficeAgent |
| GET | `/accounts/{id}` | Fetch an account with computed loyalty tier | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/accounts` | List accounts | BoxOfficeAgent, FinanceClerk |
| POST | `/accounts/{id}/suspend` | Suspend an account | BoxOfficeAgent |
| GET | `/accounts/{id}/subscriptions` | List subscriptions for an account | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/season-plans` | Create a season plan template | BoxOfficeAgent |
| GET | `/season-plans/{id}` | Fetch a season plan | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/season-plans` | List season plans | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/subscriptions` | Create a PENDING subscription | BoxOfficeAgent |
| GET | `/subscriptions/{id}` | Fetch a subscription | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/subscriptions` | List subscriptions | BoxOfficeAgent, FinanceClerk |
| POST | `/subscriptions/{id}/activate` | Activate a PENDING subscription | BoxOfficeAgent |
| POST | `/subscriptions/{id}/relocate` | Begin a seat relocation | BoxOfficeAgent |
| POST | `/subscriptions/{id}/relocate/confirm` | Confirm relocation onto target seats | BoxOfficeAgent |
| POST | `/subscriptions/{id}/relocate/abort` | Abort an in-progress relocation | BoxOfficeAgent |
| POST | `/subscriptions/{id}/renewal/offer` | Offer renewal to the holder | BoxOfficeAgent |
| POST | `/subscriptions/{id}/renewal/accept` | Accept the renewal offer | AccountHolder |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | BoxOfficeAgent |
| POST | `/seat-assignments` | Assign a seat to a PENDING subscription | BoxOfficeAgent |
| GET | `/seat-assignments/{id}` | Fetch a seat assignment | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/seat-assignments` | List seat assignments | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/subscriptions/{id}/seat-assignments` | List seat assignments under a subscription | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/payment-plans` | Create an installment plan | FinanceClerk |
| GET | `/payment-plans/{id}` | Fetch a payment plan | FinanceClerk, AccountHolder, BoxOfficeAgent |
| GET | `/payment-plans` | List payment plans | FinanceClerk, BoxOfficeAgent |
| GET | `/payment-plans/{id}/installments` | List installments of a plan | FinanceClerk, AccountHolder, BoxOfficeAgent |
| GET | `/installments/{id}` | Fetch a single installment | FinanceClerk, AccountHolder, BoxOfficeAgent |
| POST | `/payment-plans/{id}/installments/{seq}/pay` | Pay a scheduled installment | FinanceClerk |
| POST | `/payment-plans/{id}/default` | Declare a payment plan in default | FinanceClerk |
| POST | `/ticket-transfers` | Create a forward or resale | AccountHolder |
| GET | `/ticket-transfers/{id}` | Fetch a transfer | AccountHolder, BoxOfficeAgent |
| GET | `/ticket-transfers` | List transfers | AccountHolder, BoxOfficeAgent |
| POST | `/ticket-transfers/{id}/forward` | Execute a forward (gift) transfer | AccountHolder |
| POST | `/ticket-transfers/{id}/list` | List a resale transfer on the marketplace | AccountHolder |
| POST | `/ticket-transfers/{id}/complete-sale` | Complete a marketplace resale | BoxOfficeAgent |
| POST | `/ticket-transfers/{id}/cancel` | Cancel a pending or listed transfer | AccountHolder |
| POST | `/parking-zones` | Create a parking zone | BoxOfficeAgent |
| GET | `/parking-zones/{id}` | Fetch a parking zone | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/parking-zones` | List parking zones | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/parking-addons` | Add a parking pass to a subscription | BoxOfficeAgent, AccountHolder |
| GET | `/parking-addons/{id}` | Fetch a parking add-on | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/parking-addons` | List parking add-ons | BoxOfficeAgent, AccountHolder, FinanceClerk |
| GET | `/subscriptions/{id}/parking-addons` | List parking add-ons under a subscription | BoxOfficeAgent, AccountHolder, FinanceClerk |
| POST | `/_accounts/{id}/grant-points` | Test/admin: set an account's priority points directly | BoxOfficeAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SECTION_MISMATCH` | 422 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEAT_WINDOW_CONFLICT` | 409 |
| `ERR_PARKING_ZONE_FULL` | 409 |
| `ERR_TRANSFER_NOT_ELIGIBLE` | 409 |
| `ERR_PAYMENT_PLAN_EXISTS` | 409 |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 |
| `ERR_VALIDATION_FROM_TERMINAL` | 409 |
