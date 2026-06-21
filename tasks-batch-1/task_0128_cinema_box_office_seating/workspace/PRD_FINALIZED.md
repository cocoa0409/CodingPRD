# Cinema Box Office & Seating API — Product Requirements Document

## 1. Introduction

This document specifies the Cinema Box Office & Seating API, the transactional backbone of a multi-auditorium cinema operation. The platform brings together everything that happens between a film being booked and the distributor being paid: scheduling screenings into physical rooms, materializing a reserved seat map for each screening, quoting and locking ticket prices under dynamic and matinee pricing, bundling concession combos, rewarding members through a loyalty programme, settling a sliding film-rental split with each distributor, and handling the everyday realities of refunds, exchanges, and private group rentals.

Three forces make this domain demanding. First, seats are a finite pool: a single seat may be free, briefly held while a customer decides, or sold, and the system must never let two buyers walk away believing they hold the same seat. Because seat availability on a screening can be moved by any concurrent sale, reservation requests are guarded by optimistic concurrency so that a buyer acting on a stale view of the room is turned away before any seat is touched. Second, money is computed twice — once provisionally when seats are held, and again definitively when payment is captured — because a manager may re-price a screening in between. Third, a single managerial action such as cancelling a screening can fan out into a cascade of refunds, voided tickets, released seats, and reversed loyalty, all of which must settle consistently in one step.

The remainder of this document defines the system-wide contract (Section 2), the business workflows and the rules scattered through them (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request, with a single exception noted below, must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they are acting. The system recognizes exactly five roles, spelled precisely as follows: `CinemaManager`, `BoxOfficeAgent`, `Member`, `Distributor`, and `Anonymous`. If either header is missing, or `X-User-Role` is not one of these known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The only operation reachable without authentication is member self-registration; an `Anonymous` caller may register a new member and do nothing else. All other endpoints require valid headers.

Two of the roles are **entity-backed**, meaning their `X-User-ID` is the identity of a persisted record and is used for ownership checks:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare the resource's `member_id` to `X-User-ID`. A member may create and operate only their own orders and read only their own member record, orders, and tickets; acting on another member's resource is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting `Distributor`. Ownership checks on a settlement compare the settlement's `distributor_id` to `X-User-ID`; a distributor may read only its own films, showtimes, and settlements, and acting outside that scope is rejected with `ERR_NOT_RESOURCE_OWNER`.

The other three roles carry an **opaque** identity. When `X-User-Role` is `CinemaManager`, `BoxOfficeAgent`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `CinemaManager` is the operator who schedules screenings and configures films, pricing, combos, distributors, and auditoriums, and who cancels, closes, and settles. A `BoxOfficeAgent` is front-desk staff who create, pay for, cancel, refund, and exchange orders on behalf of members.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in this system carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource, including mutations that occur as part of a cascade.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by 1 on every mutation. It is the basis for optimistic concurrency control described in Section 2.5.

Two entities are deliberately leaner. A `Distributor` carries only `id` and `created_at` — it has no `updated_at` and no `version`. Likewise a `Seat` carries only `id` and `created_at` and has neither `updated_at` nor `version`; seat state is reflected through its computed `occupancy` field rather than through versioning. Every other entity — `Auditorium`, `Film`, `Showtime`, `Member`, `ConcessionCombo`, `Order`, `Ticket`, `Payment`, and `Settlement` — carries the full set including `updated_at` and `version`.

A `Showtime`'s `version` deserves special mention: it advances not only on its own status changes but whenever its seat counts move — that is, on every seat hold, sale, release, and on status changes. This is what makes the showtime the concurrency anchor for seat sales (Section 2.5).

### 2.5. Optimistic Concurrency Control on Showtimes

Two operations mutate a showtime based on the client's prior view of its seat availability, and both are protected against acting on stale data. In each case the request body must carry `expected_showtime_version`, the `version` of the target `Showtime` the client last observed.

When a client creates an order against a showtime, the request must carry `expected_showtime_version` matching that showtime's current `version`. If another writer has held or sold seats on the same showtime since the client last read it — legitimately advancing the showtime's seat counts and `version` — the create is rejected with `ERR_STALE_SHOWTIME_VERSION` (HTTP 412), and no seat is held. This forces the client to re-read current seat availability before reserving.

When a manager cancels a showtime, the request must likewise carry `expected_showtime_version` matching the showtime's current `version`. If the version has advanced since the manager last observed it — for example because a batch of sales landed after they decided to cancel — the cancel is rejected with `ERR_STALE_SHOWTIME_VERSION` (HTTP 412), forcing a re-read so that the cancel's downstream refund cascade always acts on the current sales set.

These are the only two endpoints that take a version field. No other endpoint accepts or requires `expected_showtime_version`.

### 2.6. Cascading Mutations and Hierarchical Consistency

Several operations mutate more than one entity in a single step. When this happens, every affected entity has its `updated_at` refreshed and, where it carries one, its `version` incremented — including a showtime whose seat counts change as a side effect. The precise cascade for each operation (cancelling a showtime, refunding or exchanging an order, expiring or cancelling a held order, paying an order) is specified in the workflow narratives of Section 3; the governing principle here is that these cascades are atomic and that the server may transition child resources automatically, without a separate client request on each one.

A showtime's seat-derived figures are computed, not directly written by clients: `seats_sold` is the count of tickets on the showtime in `SOLD` state, `seats_held` is the count of tickets in `HELD` state that have not expired, and `gross_receipts_cents` is the sum of `final_price_cents` over the showtime's sold, non-refunded tickets. A seat's `occupancy` is derived from the ticket currently bound to it and is one of `FREE`, `HELD`, or `SOLD`.

### 2.7. Nested Resource Retrieval and Reference Validation

Many paths address a resource nested beneath a parent (for example, a showtime nested under an auditorium, or seats, orders, and the settlement nested under a showtime). For any such request, the system validates the path identifiers from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. The same existence requirement applies to foreign-key references supplied in a request body — a referenced auditorium, film, showtime, seat, order, member, combo, distributor, or settlement that does not exist yields `ERR_NOT_FOUND`.

When more than one condition could reject a request, the checks are applied in a fixed precedence so that a deterministic error surfaces. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then resource-ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`), then existence of every referenced resource (`ERR_NOT_FOUND`), then the target's state being valid for the requested transition (`ERR_INVALID_STATE`), then the optimistic-concurrency version check (`ERR_STALE_SHOWTIME_VERSION`), and only then the domain-specific business rules. Within the business-rule band the order is likewise fixed: the matinee-window check precedes the auditorium double-booking check, which precedes the rental-fee check; for order placement, the seat-belongs-to-showtime check precedes the seat-availability check, which precedes the empty-selection check, which precedes the member-overlap check, which precedes the rental-no-seat-sales check; the wallet-balance check, the past-showtime check, the split-schedule check, the close-readiness check, and the baseline request-shape check (`ERR_INVALID_REQUEST`) follow in that relative order. A given endpoint runs only the subset of these checks that applies to it, but always in this relative order.

### 2.8. Monetary Values, Pricing Profiles, and Rounding

All monetary amounts in this system are integer counts of cents, named with a `_cents` suffix. Wherever a calculation multiplies a cent amount by a fractional rate or multiplier, the result is rounded to a whole number of cents using the **round half up** convention (a value exactly halfway between two integers rounds upward). The order of operations matters and is fixed per calculation; the specific rounding boundaries are given alongside each formula in Section 3.

Across every write operation, the system also performs a baseline request-shape check: required body fields must be present and well-typed, and any enumerated field must carry a value drawn from its declared set. A request that omits a required field, supplies a value of the wrong type, or uses an out-of-set enum value is rejected with `ERR_INVALID_REQUEST`.

A screening's price is shaped by its **pricing profile**, an enumerated value on the showtime that is one of `STANDARD`, `MATINEE`, or `PEAK`. Each profile selects a multiplier applied to the base fare: `STANDARD` multiplies by 1.00, `MATINEE` by 0.70, and `PEAK` by 1.30. The `MATINEE` profile is time-restricted: it may be selected only when the showtime's local start hour is strictly before 17 (5 PM); for the purposes of this rule, `starts_at` is treated as UTC-local. Seat class adds a flat surcharge on top of the profile-adjusted base, described where seat pricing is detailed in Section 3.

### 2.9. Loyalty, Tiers, and the Member Wallet

Members accrue loyalty over their purchasing lifetime. A member's `loyalty_points` is a lifetime balance that rises when tickets are paid for and falls when an order is refunded or exchanged, and from that balance the member's `tier` is derived as one of `BRONZE`, `SILVER`, or `GOLD`. Tier governs concession discounts. The exact accrual rate, reversal rule, and tier breakpoints are specified in Section 3.

Separately, each member has a `wallet_credit_cents` balance of refundable store credit. It is credited when an order is refunded to the wallet and when an exchange produces a price reduction, and it is debited when a member elects to apply it to an order at payment. The wallet balance can never go negative.

### 2.10. Auditorium Turnaround and Schedule Integrity

Each auditorium declares a `turnaround_minutes` cleaning buffer that must elapse after one screening ends before the next may begin in that same room. When a new screening is scheduled, the system treats each screening's occupancy as the half-open interval from its `starts_at` up to but not including its `ends_at`, and additionally reserves the turnaround buffer after the end. A new screening may not overlap any existing non-cancelled screening in the same auditorium once the buffer is taken into account. The schedule-integrity and double-booking rules are detailed where scheduling is described in Section 3.

## 3. Business Logic & Workflows

### 3.1. Setting the Stage: Auditoriums, Distributors, and Films

A `CinemaManager` lays the groundwork before any tickets can be sold. An **auditorium** is created with a display `name` and a `seat_count` that must be at least 1; the count defines the size of the seat map that every screening in the room will materialize. An auditorium also accepts an optional `turnaround_minutes` buffer, which must be zero or greater and defaults to 20 minutes when omitted. Auditoriums have a `status` that is always `ACTIVE` — there is no retirement workflow in this system.

A **distributor** is the film-rights holder entitled to a share of receipts. It is created with a `name` and an optional `minimum_guarantee_cents` floor — the minimum the distributor is owed per settlement regardless of what the percentage computation produces — which must be zero or greater and defaults to 0.

A **film** is created with a `title`, a `runtime_minutes` of at least 1, the `distributor_id` of its rights holder, a `release_date` (the ISO 8601 UTC instant of theatrical release, against which a screening's week index is measured), and a `split_schedule`. The split schedule is an ordered array of sliding-scale rental terms, each pairing a `week_index` (a zero-based count of weeks since release) with a `distributor_pct`. The schedule must contain a term whose `week_index` is 0, and every `distributor_pct` must lie between 0 and 1 inclusive; a schedule missing the week-0 term or carrying any percentage outside that range is rejected with `ERR_INVALID_SPLIT_SCHEDULE`. A film's `status` begins at `BOOKING` and advances to `RUNNING` and finally `ENDED`. A manager may end a film's run, moving it from `RUNNING` to `ENDED`; this is permitted only while the film is `RUNNING` and only when no screening of that film remains in either `SCHEDULED` or `ON_SALE` state, otherwise the request is rejected with `ERR_INVALID_STATE`.

### 3.2. Scheduling a Screening and Materializing the Seat Map

Within an auditorium, a `CinemaManager` schedules a **showtime** by supplying the `film_id`, the `starts_at` instant, a `pricing_profile`, a `base_price_cents` per-seat base fare (zero or greater), and optionally a `rental_basis` and `private_rental_fee_cents`. The showtime's room is recorded as its `auditorium_id`. The system computes the screening's `ends_at` as the start instant plus the film's `runtime_minutes` plus a fixed trailer-and-cleaning pad of 15 minutes; this end instant defines the half-open occupancy interval used for overlap math. A newly scheduled showtime starts in `SCHEDULED` status.

Scheduling enforces several rules. If the chosen profile is `MATINEE` but the screening's local start hour is 17 or later, the request is rejected with `ERR_MATINEE_WINDOW_VIOLATION`. The new screening, together with its trailing turnaround buffer drawn from the auditorium's `turnaround_minutes`, must not overlap the half-open interval of any existing non-cancelled screening in the same room; an overlap is rejected with `ERR_AUDITORIUM_DOUBLE_BOOKED`. The `rental_basis` is either `BOX_OFFICE` (the default, where receipts are split per-seat) or `RENTAL` (a private buyout at a flat fee); a `RENTAL` screening must carry a positive `private_rental_fee_cents`, while a `BOX_OFFICE` screening must carry a fee of exactly 0, and any other combination is rejected with `ERR_RENTAL_FEE_INVALID` (the field defaults to 0 when omitted). As the showtime is created, the system materializes the seat map: it creates one `Seat` row per physical seat, exactly as many as the auditorium's seat count.

Each seat records its `showtime_id`, a `row_label` (such as "A"), a one-based `seat_number` of at least 1, and a `seat_class` that is one of `STANDARD`, `PREMIUM`, or `ACCESSIBLE` (defaulting to `STANDARD`). The seat class drives a flat surcharge added on top of the profile-adjusted base fare: `STANDARD` and `ACCESSIBLE` add nothing, while `PREMIUM` adds 400 cents. Every freshly created seat begins with an `occupancy` of `FREE`.

A manager may **re-price** a showtime that is still `SCHEDULED` or `ON_SALE`, supplying a new `pricing_profile`, a new `base_price_cents`, or both. Re-pricing updates the stored profile and base fare and increments the showtime's `version`. Because final ticket prices are read from the showtime at payment time (Section 3.5), a re-price between hold and payment changes what a customer ultimately pays.

To put a scheduled screening on sale, a manager opens it, advancing it from `SCHEDULED` to `ON_SALE`. Opening is permitted only when the showtime is currently `SCHEDULED` and the film is in `BOOKING` or `RUNNING` status, and — for a `RENTAL` screening — only when its `private_rental_fee_cents` is greater than 0. The first time any screening of a film is opened, the film bubbles up from `BOOKING` to `RUNNING` as a side effect, and opening increments the showtime's `version`.

### 3.3. Members, Combos, and the Loyalty Programme

Anyone may **register a member**, supplying an `email` (the unique login/contact address) and a `full_name`; this is the sole operation an `Anonymous` caller may perform, though staff may also register members on a walk-up basis. A new member starts with `loyalty_points` of 0, a `tier` of `BRONZE`, and a `wallet_credit_cents` balance of 0.

Loyalty accrues only on ticket spend, never on concessions. When an order is paid, the member earns one point for every full 100 cents of the order's ticket subtotal — that is, the points earned equal the ticket subtotal in cents divided by 100, with any remainder discarded (floored to a whole number). The exact same number of points that were granted for an order is subtracted again if that order is later refunded or exchanged. After every accrual or reversal, the member's `tier` is re-derived from the resulting lifetime `loyalty_points` balance using these breakpoints, evaluated against the balance with at-least (greater-than-or-equal) semantics: the member is `GOLD` when the balance is at least 200 points, otherwise `SILVER` when the balance is at least 50 points, otherwise `BRONZE`. Because reversals reduce the balance, a refund or exchange can demote a member's tier.

A **concession combo** is created by a manager with a `name`, a `price_cents` list price (zero or greater), and an optional `member_discount_pct`, a fraction between 0 and 1 inclusive (defaulting to 0) that applies only to members of tier `SILVER` or `GOLD`. A combo's `status` is always `AVAILABLE`; combos are configuration and are never retired in this system.

### 3.4. Reserving Seats: Creating a Held Order

A purchase begins when a `BoxOfficeAgent` or a `Member` creates an **order** against an on-sale showtime, reserving seats and placing held tickets. The request identifies the purchasing member via `member_id`, lists the requested `seat_ids`, optionally lists `combo_ids` to bundle (defaulting to an empty list), optionally sets `apply_wallet_credit` (defaulting to false), and carries `expected_showtime_version` for the stale-view check described in Section 2.5. A member may create an order only for their own `member_id`; every order has a member, and walk-up sales with no member are not allowed. The new order's `showtime_id` records the screening, and the order begins in `HELD` status.

The reservation is subject to a sequence of checks. Beyond the authentication, role, ownership, existence, and stale-version checks already described, the system requires that at least one seat be requested — an empty `seat_ids` array is rejected with `ERR_NO_SEATS_SELECTED`. Every requested seat must belong to the order's showtime; a seat that is not part of that screening's map is rejected with `ERR_SEAT_NOT_ON_SHOWTIME`. Each requested seat must currently be `FREE` — not held or sold by another live order — and a seat that is already taken is rejected with `ERR_SEAT_UNAVAILABLE`. A `RENTAL` screening cannot be sold seat by seat at all; any per-seat order against a rental screening is rejected with `ERR_RENTAL_NO_SEAT_SALES`. Finally, the purchasing member must not already hold a live order — one in `HELD` or `PAID` status — on a *different* showtime whose half-open interval overlaps this screening's interval, because a member cannot be seated at two films simultaneously; such a clash is rejected with `ERR_MEMBER_DOUBLE_BOOKED`. Note that this member overlap is a pure half-open interval test with no buffer, distinct from the auditorium double-booking check, which additionally reserves the turnaround buffer.

When these checks pass, the system places one `HELD` `Ticket` per requested seat and flips each of those seats from `FREE` to `HELD` occupancy. Each ticket records its `order_id`, its denormalized `showtime_id` and `member_id`, and the `seat_id` it occupies. Each ticket is quoted a **provisional price** at this moment, stored on `provisional_price_cents`: the showtime's current base fare is multiplied by the profile multiplier for its current pricing profile and the product is rounded half up to whole cents, after which the seat-class surcharge is added as an integer (multiply and round first, then add the surcharge). The order's `hold_expires_at` is set to 15 minutes after the moment of creation; a held order that is not paid by that instant expires automatically. Creating the order increments the showtime's `version`. The order's monetary totals — `tickets_subtotal_cents`, `combos_subtotal_cents`, `wallet_applied_cents`, and `total_charged_cents` — are not computed at hold; each begins at 0 and stays 0 while the order is `HELD`, taking its computed value only at payment (Section 3.5).

### 3.5. Paying, Pricing, and the Order Total

A held order is paid by a `BoxOfficeAgent` or by the owning `Member`, locking prices and capturing payment. Payment is permitted only when the order is still `HELD`, the current time is strictly before its `hold_expires_at`, the showtime is `ON_SALE`, and every seat in the order is still held by *this* order. An attempt to pay an order that is not in a payable state is rejected with `ERR_INVALID_STATE`.

At payment, each ticket's **final price** is locked into `final_price_cents` using the same shape as the provisional quote but re-read from the showtime's *current* profile and base fare: the current base fare times the current profile multiplier, rounded half up to whole cents, plus the seat-class surcharge as an integer. Because a manager may have re-priced the showtime between hold and payment, the final price may differ from the provisional one. Each ticket then transitions from `HELD` to `SOLD`, and each bound seat's `occupancy` becomes `SOLD`.

The order total is then computed in a pinned order of operations. First, `tickets_subtotal_cents` is the sum of the just-locked `final_price_cents` across the order's tickets. Second, `combos_subtotal_cents` is computed combo by combo: for a member whose tier is `SILVER` or `GOLD`, each combo's charge is its `price_cents` minus the combo's `member_discount_pct` of that price rounded half up to whole cents, and these per-combo discounted prices are summed; the per-combo discount is rounded before the sum, never the other way around. For a `BRONZE` member the `member_discount_pct` is ignored entirely and every combo is charged at list price. Third, the gross amount due is the ticket subtotal plus the combo subtotal. Fourth, if `apply_wallet_credit` is true, the wallet amount applied is the smaller of the member's `wallet_credit_cents` balance and that gross due, recorded as `wallet_applied_cents`; if the flag is false, the applied amount is 0. Fifth, `total_charged_cents` is the gross due minus the wallet applied. The applied wallet amount may not exceed the member's wallet balance; an over-claim is rejected with `ERR_INSUFFICIENT_WALLET_CREDIT`.

Paying the order produces several effects in one step. The order advances from `HELD` to `PAID`. Exactly one `Payment` is created in `CAPTURED` status, whose `amount_cents` equals the order's `total_charged_cents` and whose `refunded_cents` begins at 0. If the wallet was applied, the member's `wallet_credit_cents` is reduced by `wallet_applied_cents`. The member's loyalty is accrued as described in Section 3.3 — one point per full 100 cents of the ticket subtotal — and the member's `tier` is re-derived from the new balance. Finally, because the showtime's seats-sold and gross-receipts figures have changed, its `version` is incremented.

### 3.6. The Hold Clock: Expiry and Cancellation

A held order lives only until its `hold_expires_at`. When the current time reaches or passes that instant while the order is still `HELD`, the order auto-expires: it moves to `EXPIRED`, each of its tickets is `VOIDED`, each held seat returns to `FREE` occupancy, and the showtime's `version` is incremented. This expiry is evaluated lazily — when an order or its showtime is read, any past-TTL held order is expired before counts are computed — and it can also be driven explicitly. An administrative test-driving capability advances the server's logical current UTC instant to a supplied `to_iso8601` value; advancing the clock triggers a sweep that expires every held order whose `hold_expires_at` has been reached or passed.

Before the deadline, a held order may be **cancelled** by a `BoxOfficeAgent` or the owning `Member`. Cancellation is permitted only while the order is `HELD`; it moves the order to `CANCELLED`, voids each ticket, returns each seat to `FREE`, and increments the showtime's `version`. Both `EXPIRED` and `CANCELLED` are terminal for a held order, and in both cases the tickets are `VOIDED` and the seats released — the difference is only the trigger (the lapse of the hold clock versus an explicit cancel request).

### 3.7. Refunds and Exchanges

Once an order is `PAID`, a `BoxOfficeAgent` may **refund** it. A refund is permitted only while the order is `PAID`, and — outside of a showtime-cancel cascade — only while the showtime is in `ON_SALE` or `CANCELLED` status and the current time is strictly before the showtime's `starts_at`. A refund attempted at or after the screening's start, outside a cancel cascade, is rejected with `ERR_PAST_SHOWTIME`. The refund request carries a `refund_destination` indicating where the money goes. Refunding moves the order to `REFUNDED` and cascades as follows: the order's payment has its `refunded_cents` increased by the refunded amount and its `status` set to `REFUNDED`; if the destination is the original payment method, the funds return to the payer, whereas if the destination is the wallet, the member's `wallet_credit_cents` is credited by the refunded amount; every ticket on the order is `VOIDED` and every bound seat returns to `FREE`; the loyalty points originally accrued for this order are subtracted from the member's `loyalty_points` and the member's `tier` is re-derived; and the showtime's `version` is incremented.

Alternatively, a `BoxOfficeAgent` may **exchange** a paid order's seats for seats on a different screening. An exchange is permitted only while the order is `PAID`, and — like a refund — only before the original showtime's start, otherwise it is rejected with `ERR_PAST_SHOWTIME`. The request supplies the target screening's `new_showtime_id` and the desired `new_seat_ids` on it. The target showtime must be `ON_SALE` with the current time before its `starts_at`, and every requested new seat must currently be `FREE` on the target; as with order creation, the new seats must belong to the target screening (otherwise `ERR_SEAT_NOT_ON_SHOWTIME`), at least one seat must be requested (otherwise `ERR_NO_SEATS_SELECTED`), and an already-taken seat is rejected with `ERR_SEAT_UNAVAILABLE`. The exchange moves the original order to `EXCHANGED`, a terminal status; its old tickets are `VOIDED` and their seats returned to `FREE`; and a new `HELD` successor order is created on the target screening holding the new seats. The price difference is settled by comparing the new tickets' subtotal to the old: if the new subtotal is greater, the successor order carries the delta as the amount due, while if it is smaller, the difference is credited to the member's `wallet_credit_cents`. The loyalty accrued for the original order is reversed at exchange time, and the successor order accrues fresh loyalty only when it is itself paid. Both the original and the target showtimes have their `version` incremented.

### 3.8. Cancelling a Screening: The Full Cascade

A `CinemaManager` may **cancel** a screening that is either `SCHEDULED` or `ON_SALE`, supplying `expected_showtime_version` for the stale-view guard of Section 2.5. Cancellation is rejected with `ERR_INVALID_STATE` if the screening is in any other status. The screening moves to `CANCELLED`, a terminal status, and the consequences differ by where it started.

Cancelling a `SCHEDULED` screening is the simple case: no orders exist yet, so the system merely releases any pre-created seats back to `FREE` occupancy and increments the showtime's `version`.

Cancelling an `ON_SALE` screening unwinds all live commitments in one atomic step. Every `PAID` order on the screening is refunded in full (driving each through its own refund cascade — payment marked refunded, tickets voided, seats freed, and loyalty reversed, exactly as in Section 3.7, except that this cascade is permitted even after the screening's start because it originates from the cancel). The cancel cascade names no refund destination, so each such refund returns the funds to the original payment method; it never credits the member's `wallet_credit_cents`. Every `HELD` order on the screening is moved to `CANCELLED`, releasing its held seats. Every ticket on the screening, whether it was `HELD` or `SOLD`, is `VOIDED`, and every seat on the screening returns to `FREE`. The showtime's `version` is incremented to reflect the cascade.

### 3.9. Closing the Screening and Settling the Distributor Split

After a screening has run, a `CinemaManager` **closes** it, advancing it from `ON_SALE` to `CLOSED` — a terminal status. Closing is permitted only when the screening is `ON_SALE`, the current time is at or past its `ends_at`, and no order on the screening is still `HELD`; an attempt before the screening is over or while a held order remains is rejected with `ERR_SHOWTIME_NOT_OVER`. Closing creates exactly one `Settlement` for the screening and increments the showtime's `version`.

The settlement records the screening via `showtime_id`, denormalizes the `film_id` and `distributor_id` at close time, and computes the financial split. For a `BOX_OFFICE` screening, the settlement's `gross_receipts_cents` is a snapshot of the showtime's gross receipts at close. The system first computes the screening's **week index**: the number of whole weeks between the film's `release_date` and the screening's `starts_at`, taken as the elapsed time divided by seven days and floored to a whole number, but never less than 0. From the film's `split_schedule`, the system selects the `applied_distributor_pct` as the percentage attached to the term with the greatest `week_index` that is still less than or equal to the screening's week index — so the distributor's share slides downward as the film ages. The sliding distributor amount is the gross receipts multiplied by that selected percentage, rounded half up to whole cents. The settlement's `distributor_share_cents` is then the larger of that sliding amount and the distributor's `minimum_guarantee_cents` floor. The `house_share_cents` is the gross receipts minus the distributor share, which may be negative if the minimum guarantee exceeds the gross.

For a `RENTAL` screening, there are no per-seat receipts; instead the settlement's `gross_receipts_cents` is the screening's `private_rental_fee_cents`, the `applied_distributor_pct` is the fixed rental cut of 0.10, the `distributor_share_cents` is that flat fee multiplied by 0.10 rounded half up to whole cents, and the `house_share_cents` is the flat fee minus that distributor share.

### 3.10. Reading the System: Ownership-Scoped Views

Beyond the write workflows, the system exposes read access scoped by role. A `CinemaManager` and a `BoxOfficeAgent` can read auditoriums, films, showtimes, seats, orders, tickets, payments, and combos broadly. A `Member` can read their own member record, their own orders, and their own tickets, along with showtimes, seats, and combos. A `Distributor` can read its own distributor record, its own films and showtimes, and its own settlements. List endpoints accept the usual `limit` and `offset` pagination parameters and a variety of filters that narrow results without exposing other principals' data: auditoriums, showtimes, seats, orders, tickets, combos, and films may be filtered by `status`; showtimes may be filtered by `film_id`; seats by `occupancy`; films, showtimes, and settlements by `distributor_id`; orders and tickets by `member_id`; tickets and settlements by `showtime_id`; tickets by `seat_id` and by `state`; settlements by `film_id`. Reading an order or a showtime first lazily expires any past-TTL held orders so that the returned counts and states reflect the hold clock.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource, including state transitions, return a `200 OK` status code. The clock-advance test-driving capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/auditoriums` | Create an auditorium | CinemaManager |
| GET | `/auditoriums/{id}` | Get an auditorium | CinemaManager, BoxOfficeAgent |
| GET | `/auditoriums` | List auditoriums | CinemaManager, BoxOfficeAgent |
| POST | `/distributors` | Create a distributor | CinemaManager |
| GET | `/distributors/{id}` | Get a distributor | CinemaManager, Distributor |
| POST | `/films` | Create a film with its sliding split schedule | CinemaManager |
| GET | `/films/{id}` | Get a film | CinemaManager, BoxOfficeAgent, Distributor |
| GET | `/films` | List films, filterable by distributor | CinemaManager, Distributor |
| POST | `/films/{id}/end-run` | End a film's run | CinemaManager |
| POST | `/auditoriums/{id}/showtimes` | Schedule a showtime; materializes the seat map | CinemaManager |
| GET | `/auditoriums/{id}/showtimes` | List showtimes in an auditorium | CinemaManager, BoxOfficeAgent |
| GET | `/showtimes/{id}` | Get a showtime | CinemaManager, BoxOfficeAgent, Member |
| GET | `/showtimes` | List showtimes, filterable by film | CinemaManager, BoxOfficeAgent, Distributor |
| POST | `/showtimes/{id}/open` | Put a scheduled showtime on sale | CinemaManager |
| PATCH | `/showtimes/{id}/pricing` | Re-price a scheduled or on-sale showtime | CinemaManager |
| POST | `/showtimes/{id}/cancel` | Cancel a showtime; cascades refunds and seat release | CinemaManager |
| POST | `/showtimes/{id}/close` | Close a finished showtime and settle the split | CinemaManager |
| GET | `/showtimes/{id}/seats` | Get the seat map for a showtime | CinemaManager, BoxOfficeAgent, Member |
| GET | `/showtimes/{id}/orders` | List orders on a showtime | CinemaManager, BoxOfficeAgent |
| GET | `/showtimes/{id}/settlement` | Get the settlement created at close | CinemaManager, Distributor |
| POST | `/members` | Register a member (no auth required) | Anonymous, CinemaManager, BoxOfficeAgent |
| GET | `/members/{id}` | Get a member (self or staff) | Member, CinemaManager, BoxOfficeAgent |
| POST | `/combos` | Create a concession combo | CinemaManager |
| GET | `/combos/{id}` | Get a combo | CinemaManager, BoxOfficeAgent, Member |
| GET | `/combos` | List combos | CinemaManager, BoxOfficeAgent, Member |
| POST | `/showtimes/{id}/orders` | Create a held order: reserve seats, place held tickets | BoxOfficeAgent, Member |
| GET | `/orders/{id}` | Get an order (lazily expires if past TTL) | BoxOfficeAgent, Member, CinemaManager |
| GET | `/orders` | List orders, filterable by member | BoxOfficeAgent, Member, CinemaManager |
| POST | `/orders/{id}/pay` | Pay a held order: lock final prices, capture payment, accrue loyalty | BoxOfficeAgent, Member |
| POST | `/orders/{id}/cancel` | Cancel a held order, releasing seats | BoxOfficeAgent, Member |
| POST | `/orders/{id}/refund` | Refund a paid order | BoxOfficeAgent |
| POST | `/orders/{id}/exchange` | Exchange a paid order's tickets to a new showtime/seats | BoxOfficeAgent |
| GET | `/orders/{id}/tickets` | List tickets on an order | BoxOfficeAgent, Member, CinemaManager |
| GET | `/orders/{id}/payments` | List payments on an order | BoxOfficeAgent, CinemaManager |
| GET | `/tickets/{id}` | Get a single ticket | BoxOfficeAgent, Member, CinemaManager |
| GET | `/tickets` | List tickets, filterable by member, showtime, or seat | BoxOfficeAgent, Member, CinemaManager |
| GET | `/settlements/{id}` | Get a single settlement | CinemaManager, Distributor |
| GET | `/settlements` | List settlements, filterable by distributor, film, or showtime | CinemaManager, Distributor |
| POST | `/_clock/advance` | Set the server's current UTC instant (test-driving) | CinemaManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SHOWTIME_VERSION` | 412 |
| `ERR_MATINEE_WINDOW_VIOLATION` | 422 |
| `ERR_AUDITORIUM_DOUBLE_BOOKED` | 409 |
| `ERR_RENTAL_FEE_INVALID` | 422 |
| `ERR_SEAT_NOT_ON_SHOWTIME` | 422 |
| `ERR_SEAT_UNAVAILABLE` | 409 |
| `ERR_NO_SEATS_SELECTED` | 422 |
| `ERR_MEMBER_DOUBLE_BOOKED` | 409 |
| `ERR_RENTAL_NO_SEAT_SALES` | 409 |
| `ERR_INSUFFICIENT_WALLET_CREDIT` | 422 |
| `ERR_PAST_SHOWTIME` | 409 |
| `ERR_INVALID_SPLIT_SCHEDULE` | 422 |
| `ERR_SHOWTIME_NOT_OVER` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
